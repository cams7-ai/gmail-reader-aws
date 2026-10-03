# Migração do `gmail-reader-aws` com AWS SAM no Linux

Este guia corresponde ao [`template.yaml`](../template.yaml) vigente. A função não possui API Gateway ou URL pública. O `loto-bot` a invoca diretamente com `lambda:InvokeFunction`.

## Arquitetura e segurança

Fluxo: `loto-bot` EC2 → Lambda Invoke autorizado por IAM → `GmailReaderFunction` fora da VPC do cliente → Secrets Manager e Gmail API.

- `GMAIL_READER_URL` não é usado na AWS; o consumidor recebe o ARN em `GMAIL_READER_FUNCTION_NAME`;
- não há `X-API-Key`, `INTEGRATION_API_TOKEN` ou segredo compartilhado;
- IAM autoriza o `loto-bot` a invocar somente esta função;
- a função lê somente o segredo OAuth indicado por `GmailOAuthSecretArn`;
- a função não precisa de VPC, NAT ou Security Group para alcançar Secrets Manager e Gmail.

## Pré-requisitos

- AWS CLI e SAM CLI instalados e configurados;
- Python 3.12;
- Docker instalado e em execução para builds locais compatíveis;
- projeto OAuth do Google/Gmail configurado;
- refresh token válido obtido em ambiente local;
- identidade AWS com acesso a CloudFormation, Lambda, IAM, Logs, S3 e Secrets Manager;
- mesma conta e região usadas pelo `loto-bot`, salvo configuração cross-account explícita.

Defina o perfil e a região que serão usados nos comandos:

```bash
AWS_PROFILE="<perfil>"
AWS_REGION="us-east-1"
STACK_NAME="gmail-reader"
```

## Segredo OAuth

Armazene no Secrets Manager o JSON de credenciais necessário pelo autenticador do projeto, incluindo o refresh token. Não coloque o token no template, `samconfig.toml`, `.env` versionado ou logs.

```bash
GMAIL_OAUTH_SECRET_ARN=$(aws secretsmanager create-secret \
  --name gmail-reader/google-oauth-token \
  --secret-string file://token.json \
  --query ARN --output text \
  --region "$AWS_REGION" --profile "$AWS_PROFILE")
```

Se o segredo já existir, atualize sua versão ou obtenha o ARN existente. Não versione `token.json`. Confirme que `GMAIL_OAUTH_SECRET_ARN` contém o ARN antes de prosseguir.

## Testar e validar

```bash
.venv/bin/python -m pytest
sam validate --lint --template-file template.yaml
sam build --template-file template.yaml
```

## Deploy

```bash
sam deploy \
  --template-file template.yaml \
  --stack-name "$STACK_NAME" \
  --resolve-s3 \
  --capabilities CAPABILITY_IAM \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  --parameter-overrides \
    GmailOAuthSecretArn="$GMAIL_OAUTH_SECRET_ARN" \
    WaitTimeoutSeconds=15
```

O timeout solicitado pelo consumidor deve permanecer entre 0 e 15 segundos. A Lambda tem timeout total de 25 segundos.

## Entregar o ARN ao `loto-bot`

```bash
GMAIL_READER_FUNCTION_ARN=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='FunctionArn'].OutputValue | [0]" \
  --output text --region "$AWS_REGION" --profile "$AWS_PROFILE")
printf '%s\n' "$GMAIL_READER_FUNCTION_ARN"
```

Passe o valor como `GmailReaderFunctionArn` no deploy do `loto-bot`. O bootstrap grava:

```text
GMAIL_READER_FUNCTION_NAME=<FunctionArn>
VALIDATION_CODE_WAIT_TIMEOUT_SECONDS=15
```

O nome histórico `GMAIL_READER_URL` não representa mais o contrato AWS e não deve ser configurado no ambiente implantado.

## Smoke test direto

```bash
printf '{"waitTimeoutSeconds":"15"}\n' > payload.json
aws lambda invoke \
  --function-name "$GMAIL_READER_FUNCTION_ARN" \
  --cli-binary-format raw-in-base64-out \
  --payload fileb://payload.json \
  --region "$AWS_REGION" \
  --profile "$AWS_PROFILE" \
  response.json
cat response.json
```

A resposta mantém o formato `statusCode`/`body`; isso é contrato da aplicação, não uma API HTTP pública. Não exponha nem registre o código de validação.

## Operação, rotação e rollback

```bash
FUNCTION_NAME=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --query "Stacks[0].Outputs[?OutputKey=='FunctionName'].OutputValue | [0]" \
  --output text --region "$AWS_REGION" --profile "$AWS_PROFILE")
aws logs tail "/aws/lambda/$FUNCTION_NAME" \
  --since 10m --region "$AWS_REGION" --profile "$AWS_PROFILE"
```

Rotacione o refresh token atualizando o mesmo segredo. Em uma Lambda aquecida, uma falha de refresh limpa o cache e carrega a versão atual do segredo uma vez. Teste essa recuperação antes de revogar o token antigo. Para código ou infraestrutura, rode testes, `sam build` e `sam deploy`; para rollback, reaplique uma revisão anterior. O log group mantém 14 dias de logs.

## Checklist

- [ ] Refresh token válido armazenado somente no Secrets Manager.
- [ ] Testes, `sam validate` e `sam build` aprovados.
- [ ] Nenhum evento API Gateway ou Function URL configurado.
- [ ] A função não possui `VpcConfig` nem `AWSLambdaVPCAccessExecutionRole`.
- [ ] Token rotacionado foi validado com uma invocação aquecida antes da revogação do antigo.
- [ ] Output `FunctionArn` entregue ao `loto-bot`.
- [ ] Role do consumidor limitada a este ARN.
- [ ] Role da função limitada ao segredo OAuth.
- [ ] Nenhuma chave de API compartilhada configurada.
- [ ] Alarmes, logs e orçamento revisados.
