# Migração do `gmail-reader-aws` com AWS SAM

Este guia corresponde ao [`template.yaml`](../template.yaml) vigente. A função não possui API Gateway ou URL pública. O `loto-bot` a invoca diretamente com `lambda:InvokeFunction`.

## Arquitetura e segurança

Fluxo: `loto-bot` EC2 → Lambda Invoke autorizado por IAM → `GmailReaderFunction` fora da VPC do cliente → Secrets Manager e Gmail API.

- `GMAIL_READER_URL` não é usado na AWS; o consumidor recebe o ARN em `GMAIL_READER_FUNCTION_NAME`;
- não há `X-API-Key`, `INTEGRATION_API_TOKEN` ou segredo compartilhado;
- IAM autoriza o `loto-bot` a invocar somente esta função;
- a função lê somente o segredo OAuth indicado por `GmailOAuthSecretArn`;
- a função não precisa de VPC, NAT ou Security Group para alcançar Secrets Manager e Gmail.

## Pré-requisitos

- AWS CLI e SAM CLI;
- Python 3.12;
- projeto OAuth do Google/Gmail configurado;
- refresh token válido obtido em ambiente local;
- identidade AWS com acesso a CloudFormation, Lambda, IAM, Logs, S3 e Secrets Manager;
- mesma conta e região usadas pelo `loto-bot`, salvo configuração cross-account explícita.

```powershell
$AwsProfile = "<perfil>"
$AwsRegion = "us-east-1"
$StackName = "gmail-reader"
```

## Segredo OAuth

Armazene no Secrets Manager o JSON de credenciais necessário pelo autenticador do projeto, incluindo o refresh token. Não coloque o token no template, `samconfig.toml`, `.env` versionado ou logs.

```powershell
$GmailOAuthSecretArn = aws secretsmanager create-secret `
  --name gmail-reader/google-oauth-token `
  --secret-string file://token.json `
  --query ARN --output text `
  --region $AwsRegion --profile $AwsProfile
```

Se o segredo já existir, atualize sua versão ou obtenha o ARN existente. Não versione `token.json`.

## Testar e validar

```powershell
.venv\Scripts\python.exe -m pytest
sam validate --lint --template-file template.yaml
sam build --template-file template.yaml
```

## Deploy

```powershell
sam deploy `
  --template-file template.yaml `
  --stack-name $StackName `
  --resolve-s3 `
  --capabilities CAPABILITY_IAM `
  --region $AwsRegion `
  --profile $AwsProfile `
  --parameter-overrides `
    GmailOAuthSecretArn=$GmailOAuthSecretArn `
    WaitTimeoutSeconds=15
```

O timeout solicitado pelo consumidor deve permanecer entre 0 e 15 segundos. A Lambda tem timeout total de 25 segundos.

## Entregar o ARN ao `loto-bot`

```powershell
$GmailReaderFunctionArn = aws cloudformation describe-stacks `
  --stack-name $StackName `
  --query "Stacks[0].Outputs[?OutputKey=='FunctionArn'].OutputValue | [0]" `
  --output text --region $AwsRegion --profile $AwsProfile
```

Passe o valor como `GmailReaderFunctionArn` no deploy do `loto-bot`. O bootstrap grava:

```text
GMAIL_READER_FUNCTION_NAME=<FunctionArn>
VALIDATION_CODE_WAIT_TIMEOUT_SECONDS=15
```

O nome histórico `GMAIL_READER_URL` não representa mais o contrato AWS e não deve ser configurado no ambiente implantado.

## Smoke test direto

```powershell
$Payload = @{
    waitTimeoutSeconds = "15"
} | ConvertTo-Json
$Payload | Out-File -FilePath payload.json -Encoding utf8
aws lambda invoke `
  --function-name $GmailReaderFunctionArn `
  --cli-binary-format raw-in-base64-out `
  --payload fileb://payload.json `
  --region $AwsRegion `
  --profile $AwsProfile `
  response.json
Get-Content response.json
```

A resposta mantém o formato `statusCode`/`body`; isso é contrato da aplicação, não uma API HTTP pública. Não exponha nem registre o código de validação.

## Operação, rotação e rollback

```powershell
$FunctionName = aws cloudformation describe-stacks --stack-name $StackName --query "Stacks[0].Outputs[?OutputKey=='FunctionName'].OutputValue | [0]" --output text --region $AwsRegion --profile $AwsProfile
aws logs tail "/aws/lambda/$FunctionName" --since 10m --region $AwsRegion --profile $AwsProfile
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
