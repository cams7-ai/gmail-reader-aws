# Passo a passo para migrar o `gmail-reader` para AWS com AWS SAM

Este roteiro adapta o projeto atual para uma arquitetura serverless com handler Lambda nativo, preservando o contrato do endpoint de código de validação e a Gmail API. Ele parte do guia do `mail-sender-aws`, mas trata OAuth2 do Google, token sensível, espera síncrona e ausência de disco persistente.

Premissas: Windows/PowerShell, Python 3.12, AWS CLI, SAM CLI, Docker Desktop, perfil AWS configurado e região `us-east-1`. Substitua valores entre `<...>`.

## 1. Arquitetura alvo

```text
Cliente -> API Gateway HTTP API -> Lambda Python 3.12
                                      |-> Secrets Manager (token OAuth2)
                                      |-> Gmail API (gmail.readonly)
                                      `-> CloudWatch Logs
```

O API Gateway envia eventos HTTP API payload v2.0 diretamente a um handler Lambda Python. O handler interpreta a rota e a query string, chama o serviço e devolve a resposta proxy no formato esperado pelo API Gateway. Não são necessários FastAPI, Mangum, Uvicorn, Lambda Web Adapter, EC2, ECS, Load Balancer, NAT Gateway ou VPC.

> O HTTP API possui timeout máximo de integração de 30 segundos. Como o uso será pequeno e controlado, esta migração mantém a espera síncrona, com limite total de 15 segundos para a busca. Para esperas maiores, use futuramente um fluxo assíncrono.

## 2. Mudança obrigatória na autenticação

Hoje, `GmailAuthenticator` lê `GmailAPI/token.json`, abre o navegador com `InstalledAppFlow.run_local_server()` quando necessário e grava o token em disco.

Na Lambda não existe navegador interativo, o pacote é somente leitura e `/tmp` não é persistência permanente. Autorize localmente uma vez, guarde o conteúdo completo de `token.json` no Secrets Manager e carregue-o em memória. O `refresh_token` permite renovar o `access_token` sem navegador.

## 3. Validar o ambiente

```powershell
$AwsProfile = "<perfil-aws-local>"
$AwsRegion = "us-east-1"
$StackName = "gmail-reader"
$OAuthSecretName = "gmail-reader/google-oauth-token"
$TokenPath = "file://GmailAPI/token.json"

python --version
aws --version
sam --version
docker --version
aws sts get-caller-identity --profile $AwsProfile
```

O Python deve ser 3.12.x e o STS deve retornar a conta e o ARN autenticado.

## 4. Preparar o OAuth do Google

Siga `GMAIL_API_SETUP.md` para ativar a Gmail API, configurar o consentimento, criar um cliente **Aplicativo para computador**, salvar `GmailAPI/credentials.json` e gerar `GmailAPI/token.json` mediante login local.

Mantenha somente o escopo:

```text
https://www.googleapis.com/auth/gmail.readonly
```

Valide:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
$env:PYTHONPATH = "src"
python -c "from config import Settings; from infra import GmailAuthenticator; GmailAuthenticator(Settings()).authenticate()"
```

Confirme que `token.json` contém `token`, `refresh_token`, `client_id`, `client_secret`, `token_uri` e `scopes`. Nunca versione credenciais, tokens, `.env` ou `samconfig.toml`.

## 5. Criar o segredo OAuth

Use o arquivo para não copiar o token para o histórico:

```powershell
aws secretsmanager create-secret --name $OAuthSecretName --description "Token OAuth2 do gmail-reader" --secret-string $TokenPath --region $AwsRegion --profile $AwsProfile
```

Se já existir:

```powershell
aws secretsmanager put-secret-value --secret-id $OAuthSecretName --secret-string $TokenPath --region $AwsRegion --profile $AwsProfile
```

Obtenha somente o ARN:

```powershell
$OAuthSecretArn = aws secretsmanager describe-secret --secret-id $OAuthSecretName --query ARN --output text --region $AwsRegion --profile $AwsProfile
```

Crie o segredo na região da stack. Evite `get-secret-value` no terminal, pois ele exibiria o token.

## 6. Estrutura a criar

```text
template.yaml
samconfig.local.toml
env.local.example.json
src/lambda_handler.py
src/requirements.txt
docs/AWS_SAM_MIGRATION_STEP_BY_STEP.md
```

Atualize também `.gitignore`, `pyproject.toml`, `settings.py`, `gmail_auth.py`, o serviço e os testes. Remova os módulos e testes exclusivos do FastAPI (`src/api/`) quando o handler nativo estiver coberto.

## 7. Dependências

Como o template usará `CodeUri: src/`, crie `src/requirements.txt`:

```text
boto3>=1.35,<2
google-api-python-client==2.126.0
google-auth-httplib2==0.2.0
google-auth-oauthlib==1.2.0
google-auth>=2,<3
python-dotenv>=1,<2
```

Empacote `boto3` para evitar incompatibilidades com dependências transitivas do SDK do runtime. Use `src/requirements.txt` como fonte única das dependências de runtime: o SAM lê esse arquivo ao construir `CodeUri: src/`, e o setuptools deve reutilizá-lo na instalação local.

No `pyproject.toml`, declare as dependências como dinâmicas:

```toml
[project]
dynamic = ["dependencies"]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
]

[tool.setuptools.dynamic]
dependencies = { file = ["src/requirements.txt"] }
```

Não repita no `pyproject.toml` as bibliotecas declaradas em `src/requirements.txt`. FastAPI, Mangum e Uvicorn não fazem parte da arquitetura alvo. O comando `python -m pip install -e ".[dev]"` instala as dependências de runtime e as ferramentas de teste.

## 8. Handler Lambda nativo

Crie `src/lambda_handler.py` como integração proxy nativa do HTTP API payload v2.0. O handler valida método, caminho e query string, chama diretamente o serviço de aplicação e sempre serializa `body` como string JSON:

```python
import asyncio
import json
from functools import lru_cache
import ssl
from dataclasses import replace
from functools import lru_cache
from typing import Any

from google.auth.exceptions import RefreshError

from config import Settings
from infra import GmailAuthenticator
from repositories import GmailRepository
from services import ValidationCodeService, ValidationCodeTimeoutError

MAX_WAIT_TIMEOUT_SECONDS = 15
JSON_HEADERS = {"content-type": "application/json; charset=utf-8"}


@lru_cache(maxsize=1)
def _create_repository() -> GmailRepository:
    settings = Settings()
    gmail_service = GmailAuthenticator(settings).authenticate()
    return GmailRepository(gmail_service)


def _response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": JSON_HEADERS,
        "body": json.dumps(payload, ensure_ascii=False),
        "isBase64Encoded": False,
    }


def _parse_wait_timeout_seconds(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        timeout = int(value)
    except ValueError as exc:
        raise ValueError("invalid wait timeout") from exc
    if not 0 <= timeout <= MAX_WAIT_TIMEOUT_SECONDS:
        raise ValueError("invalid wait timeout")
    return timeout


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    if http.get("method") != "GET" or http.get("path") != "/api/v1/validation-code":
        return _response(404, {"error": {"code": "NOT_FOUND", "message": "Rota não encontrada."}})

    query = event.get("queryStringParameters") or {}
    try:
        timeout = _parse_wait_timeout_seconds(query.get("waitTimeoutSeconds"))
    except ValueError:
        return _response(
            400,
            {
                "error": {
                    "code": "INVALID_WAIT_TIMEOUT_SECONDS",
                    "message": "waitTimeoutSeconds deve ser um inteiro entre 0 e 15.",
                }
            },
        )

    settings = Settings()
    if timeout is not None:
        settings = replace(settings, wait_timeout_seconds=timeout)

    try:
        service = ValidationCodeService(_create_repository(), settings)
        code = asyncio.run(service.get_validation_code())
    except ValidationCodeTimeoutError as exc:
        return _response(
            500,
            {"error": {"code": "VALIDATION_CODE_TIMEOUT", "message": str(exc)}},
        )
    except RefreshError:
        return _response(
            500,
            {
                "error": {
                    "code": "AUTHENTICATION_ERROR",
                    "message": "Falha ao autenticar na Gmail API.",
                }
            },
        )
    except (ConnectionError, TimeoutError, ssl.SSLError):
        return _response(
            500,
            {
                "error": {
                    "code": "GMAIL_API_CONNECTION_ERROR",
                    "message": "Falha temporária ao conectar à Gmail API.",
                }
            },
        )

    return _response(
        200,
        {"code": code, "message": "Código de validação encontrado com sucesso."},
    )
```

Não importe `FastAPI`, `Mangum` ou qualquer servidor ASGI. A arquitetura expõe somente `GET /api/v1/validation-code`; não existem `/docs`, `/redoc` nem `/openapi.json`.

## 9. Configurações

Adicione a `Settings`:

```python
gmail_oauth_secret_arn: str | None = field(
    default_factory=lambda: os.getenv("GMAIL_OAUTH_SECRET_ARN")
)
```

Ao sobrescrever o timeout no handler com `dataclasses.replace`, os demais campos — inclusive o ARN — são preservados automaticamente:

```python
settings = replace(settings, wait_timeout_seconds=timeout)
```

`CREDENTIALS_FILE` e `TOKEN_FILE` continuam locais. Na Lambda, o ARN tem precedência.
Valide `WAIT_TIMEOUT_SECONDS` ao carregar as configurações e rejeite valores fora
do intervalo de 0 a 15, inclusive no desenvolvimento local.

## 10. Adaptar `GmailAuthenticator`

A implementação deve carregar o segredo, desserializar o JSON, renovar o token em memória e nunca iniciar login interativo na AWS. Base:

```python
import json

import boto3
from botocore.config import Config
from google.oauth2.credentials import Credentials

_AWS_CONFIG = Config(
    connect_timeout=3,
    read_timeout=5,
    retries={"total_max_attempts": 2, "mode": "standard"},
)
@lru_cache(maxsize=1)
def _get_secrets_client():
    return boto3.client("secretsmanager", config=_AWS_CONFIG)


def _load_secret_credentials(settings):
    response = _get_secrets_client().get_secret_value(
        SecretId=settings.gmail_oauth_secret_arn
    )
    token_info = json.loads(response["SecretString"])
    return Credentials.from_authorized_user_info(
        token_info,
        list(settings.gmail_scopes),
    )
```

Integre em `_load_cached_token`. Se o ARN existir e não houver `refresh_token` válido, lance erro orientando a refazer o consentimento local. Em `_save_token`, não escreva na AWS. Mantenha o fluxo por arquivo sem ARN.

Crie o client de forma lazy e cacheada para que o modo local sem região AWS não
falhe no import. Deixe erros inesperados do SDK propagarem. O `lru_cache` de
`_create_repository()` reaproveita o serviço no mesmo ambiente Lambda.

Nunca registre `SecretString`, tokens, headers, corpo de e-mail ou códigos.

## 11. Limitar o tempo

Defina no `lambda_handler.py`:

```python
MAX_WAIT_TIMEOUT_SECONDS = 15
```

Faça `_parse_wait_timeout_seconds` rejeitar valores menores que zero ou maiores que 15 com HTTP 400 e `INVALID_WAIT_TIMEOUT_SECONDS`.

O limite precisa considerar o tempo total, não apenas os intervalos de `asyncio.sleep`. Use um deadline monotônico no serviço:

```python
from time import monotonic

deadline = monotonic() + self._settings.wait_timeout_seconds

while True:
    code, last_seen_validation_message_id = self._find_new_validation_code(
        last_received_timestamp,
        last_seen_validation_message_id,
    )
    if code:
        return code

    remaining_seconds = deadline - monotonic()
    if remaining_seconds <= 0:
        break

    await asyncio.sleep(min(1, remaining_seconds))
```

Assim, a latência das chamadas à Gmail API também consome o orçamento de 15 segundos. A consulta inicial e a autenticação acontecem antes desse trecho; por isso a Lambda terá timeout de 25 segundos, ainda abaixo dos 30 segundos do API Gateway.

## 12. Criar `template.yaml`

```yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: >-
  Gmail Reader serverless API — uses a native Lambda handler to keep the HTTP
  integration small and independent of an ASGI framework.

Metadata:
  AWSToolsMetrics:
    AWSAgentToolkit: aws-cloudformation@2
  "com.aws.cloudformation.Context":
    arch: HTTP API v2 -> native Python Lambda -> Secrets Manager + Gmail API
    must:
      - expose only GET /api/v1/validation-code during the controlled smoke test
      - add authorization before exposing the endpoint in production
      - keep OAuth credentials out of parameters and environment variables
    ref:
      - at: docs/AWS_SAM_MIGRATION_STEP_BY_STEP.md
        has: migration steps + design and security constraints
        scope: local

Parameters:
  GmailOAuthSecretArn:
    Type: String
    Description: ARN of the Secrets Manager secret containing the Gmail OAuth credentials.
    AllowedPattern: "^arn:(aws[a-zA-Z-]*)?:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:.+$"
    ConstraintDescription: Must be a valid AWS Secrets Manager secret ARN.
  SenderEmail:
    Type: String
    Description: Gmail sender address used to filter validation-code messages.
    Default: logincaixa@caixa.gov.br
  SubjectFilter:
    Type: String
    Description: Gmail subject text used to filter validation-code messages.
    Default: Código de Validação
  ActivationCodeRegex:
    Type: String
    Description: Regular expression used to extract the activation code from an email.
    Default: "Código de ativação: \\d+"
  WaitTimeoutSeconds:
    Type: Number
    Description: Maximum time the handler waits for a matching Gmail message.
    Default: 15
    MinValue: 0
    MaxValue: 15

Transform: AWS::Serverless-2016-10-31

Globals:
  Function:
    Runtime: python3.12
    Architectures: [x86_64]
    MemorySize: 256
    Timeout: 25
    Tracing: Active
    Environment:
      Variables:
        GMAIL_OAUTH_SECRET_ARN: !Ref GmailOAuthSecretArn
        SENDER_EMAIL: !Ref SenderEmail
        SUBJECT_FILTER: !Ref SubjectFilter
        ACTIVATION_CODE_REGEX: !Ref ActivationCodeRegex
        WAIT_TIMEOUT_SECONDS: !Ref WaitTimeoutSeconds

Resources:
  GmailReaderHttpApi:
    Type: AWS::Serverless::HttpApi
    Properties:
      StageName: $default

  GmailReaderFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: src/
      Handler: lambda_handler.handler
      Policies:
        - Version: "2012-10-17"
          Statement:
            - Sid: ReadGoogleOAuthSecret
              Effect: Allow
              Action: secretsmanager:GetSecretValue
              Resource: !Ref GmailOAuthSecretArn
      Events:
        ValidationCodeEndpoint:
          Type: HttpApi
          Properties:
            ApiId: !Ref GmailReaderHttpApi
            Path: /api/v1/validation-code
            Method: GET
            PayloadFormatVersion: "2.0"

  GmailReaderFunctionLogGroup:
    Type: AWS::Logs::LogGroup
    DeletionPolicy: Delete
    UpdateReplacePolicy: Delete
    Properties:
      LogGroupName: !Sub "/aws/lambda/${GmailReaderFunction}"
      RetentionInDays: 14

Outputs:
  ApiUrl:
    Description: Base URL of the Gmail Reader HTTP API.
    Value: !Sub "https://${GmailReaderHttpApi}.execute-api.${AWS::Region}.${AWS::URLSuffix}"
  FunctionName:
    Description: Name of the native Gmail Reader Lambda function.
    Value: !Ref GmailReaderFunction
```

O template recebe apenas o ARN e concede leitura exclusiva ao segredo. A única rota criada é `GET /api/v1/validation-code`, integrada diretamente a `lambda_handler.handler` com payload HTTP API v2.0. O endpoint fica sem authorizer somente para o primeiro smoke test controlado.

## 13. Configurar o SAM

Crie `samconfig.local.toml`:

```toml
version = 0.1

[default.build.parameters]
cached = true
parallel = true

[default.deploy.parameters]
stack_name = "gmail-reader"
region = "us-east-1"
capabilities = "CAPABILITY_IAM"
confirm_changeset = true
resolve_s3 = true
```

Copie para `samconfig.toml` e acrescente:

```powershell
Copy-Item samconfig.local.toml samconfig.toml
```

```toml
profile = "<perfil-aws-local>"
parameter_overrides = "GmailOAuthSecretArn=<arn-do-segredo> SenderEmail=logincaixa@caixa.gov.br WaitTimeoutSeconds=15"
```

Adicione ao `.gitignore`:

```gitignore
.aws-sam/
samconfig.toml
env.local.json
```

## 14. Testes necessários

Adicione casos para:

- respostas proxy e parsing de eventos no `lambda_handler`;
- leitura do segredo com ARN;
- fallback para arquivos locais;
- refresh em memória e erro sem `refresh_token`;
- 15 segundos aceitos e 16 rejeitados;
- ARN preservado ao sobrescrever o timeout com `dataclasses.replace`;
- ausência de segredos e códigos nos logs.

Faça patch do client AWS nos testes unitários. O projeto exige 100% de cobertura.

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

## 15. Validar e construir

```powershell
sam validate --lint
sam build
```

O build em contêiner evita artefatos Python nativos do Windows. Confirme que não há credenciais:

```powershell
Get-ChildItem .aws-sam\build -Recurse -File | Where-Object { $_.Name -in @("credentials.json", "token.json", ".env") }
```

O comando não deve retornar arquivos.

## 16. Testar com SAM local

Crie `env.local.example.json` sem dados reais:

```json
{
  "GmailReaderFunction": {
    "GMAIL_OAUTH_SECRET_ARN": "<arn-do-segredo>",
    "SENDER_EMAIL": "logincaixa@caixa.gov.br",
    "SUBJECT_FILTER": "Código de Validação",
    "ACTIVATION_CODE_REGEX": "Código de ativação: \\d+",
    "WAIT_TIMEOUT_SECONDS": "15"
  }
}
```

```powershell
Copy-Item env.local.example.json env.local.json
sam local start-api --env-vars env.local.json --profile $AwsProfile --region $AwsRegion
```

Em outro terminal:

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:3000/api/v1/validation-code?waitTimeoutSeconds=15"
```

Se o contêiner não receber credenciais AWS no Windows, valide o adaptador por teste unitário e use uma stack `dev` isolada.

## 17. Deploy e smoke test

Primeiro deploy:

```powershell
sam deploy --guided --stack-name $StackName --region $AwsRegion --profile $AwsProfile --capabilities CAPABILITY_IAM --parameter-overrides GmailOAuthSecretArn=$OAuthSecretArn SenderEmail=logincaixa@caixa.gov.br WaitTimeoutSeconds=15
```

Próximos deploys:

```powershell
sam build
sam deploy
```

Obtenha a URL e teste:

```powershell
$ApiUrl = aws cloudformation describe-stacks --stack-name $StackName --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue | [0]" --output text --region $AwsRegion --profile $AwsProfile
Invoke-RestMethod -Method Get -Uri "$ApiUrl/api/v1/validation-code?waitTimeoutSeconds=15"
sam logs --stack-name $StackName --name GmailReaderFunction --tail --region $AwsRegion --profile $AwsProfile
```

Valide também que rotas diferentes retornam HTTP 404 e que `waitTimeoutSeconds=16` retorna HTTP 400. Não há endpoints de documentação ou esquema OpenAPI.

## 18. Segurança obrigatória

O endpoint retorna um código de validação e não pode permanecer público.

- Use **AWS IAM** para workloads AWS, com SigV4.
- Use **JWT authorizer** para Cognito ou outro OIDC.
- Use **Lambda authorizer** somente para regras customizadas.

Conceda `execute-api:Invoke` apenas aos principals necessários. Aplique throttling e não grave chaves estáticas no código ou template. Como somente a rota de negócio é declarada no template, não existem endpoints de documentação a proteger.

## 19. Observabilidade, concorrência e custo

O template ativa X-Ray e retenção por 14 dias. Crie alarmes para erros, throttles, 5xx e duração P99 acima de 20 segundos.

O código registra apenas que um código foi encontrado, sem incluir o valor nos logs.

Cada chamada consulta a Gmail API repetidamente. Comece com throttling e reserved concurrency baixa. Após medir:

```yaml
ReservedConcurrentExecutions: 2
```

Configure um AWS Budget de US$ 1 ou US$ 5 e monitore quotas da Gmail API. No CI, use roles OIDC de curta duração e mantenha stacks e segredos separados por ambiente.

## 20. Checklist final

- [ ] OAuth validado localmente e `token.json` contém `refresh_token`.
- [ ] Token no Secrets Manager na região da stack.
- [ ] Nenhuma credencial versionada ou empacotada.
- [ ] Requirements e handler Lambda nativo criados, sem framework web ou servidor ASGI.
- [ ] Autenticador usa segredo na AWS e arquivo local no desenvolvimento.
- [ ] IAM permite somente `GetSecretValue` no segredo correto.
- [ ] `waitTimeoutSeconds` limitado a 15 e medido por tempo total decorrido.
- [ ] Testes aprovados com 100% de cobertura.
- [ ] Validação, build, deploy e smoke test aprovados.
- [ ] API autenticada e documentação protegida.
- [ ] Logs sem token, corpo de e-mail ou código.
- [ ] Alarmes, throttling, concorrência e budget configurados.

## 21. Atualizar o token

Se o token for revogado, refaça o consentimento local e execute:

```powershell
aws secretsmanager put-secret-value --secret-id $OAuthSecretName --secret-string $TokenPath --region $AwsRegion --profile $AwsProfile
```

Faça novo deploy para substituir ambientes ativos e execute smoke test. Não ative rotação automática genérica sem fluxo compatível com OAuth2 do Google.

## 22. Rollback e remoção

Para voltar ao modo local, deixe `GMAIL_OAUTH_SECRET_ARN` ausente.

```powershell
sam delete --stack-name $StackName --region $AwsRegion --profile $AwsProfile
```

O segredo foi criado fora da stack. Após confirmar que ninguém o usa:

```powershell
aws secretsmanager delete-secret --secret-id $OAuthSecretName --recovery-window-in-days 7 --region $AwsRegion --profile $AwsProfile
```

## Referências oficiais

- [AWS SAM CLI - instalação](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- [AWS SAM - build](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-using-build.html)
- [AWS SAM - deploy](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/using-sam-cli-deploy.html)
- [AWS SAM - Function](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-resource-function.html)
- [AWS SAM - HttpApi](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/sam-resource-httpapi.html)
- [AWS Lambda com Python](https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html)
- [AWS Lambda e Secrets Manager](https://docs.aws.amazon.com/lambda/latest/dg/with-secrets-manager.html)
- [HTTP API - quotas](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html)
- [Google OAuth para apps instalados](https://developers.google.com/identity/protocols/oauth2/native-app)
- [Gmail API - autorização](https://developers.google.com/workspace/gmail/api/auth/about-auth)
