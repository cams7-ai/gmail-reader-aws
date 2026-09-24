# Migração do `gmail-reader-aws` com AWS SAM

Este guia corresponde ao [`template.yaml`](../template.yaml) vigente. A função não possui API Gateway ou URL pública. O `loto-bot` a invoca diretamente com `lambda:InvokeFunction`.

## Arquitetura e segurança

Fluxo: `loto-bot` EC2 → endpoint privado do serviço Lambda → `GmailReaderFunction` na mesma VPC/subnet dual-stack → Secrets Manager e Gmail API por IPv6.

- `GMAIL_READER_URL` não é usado na AWS; o consumidor recebe o ARN em `GMAIL_READER_FUNCTION_NAME`;
- não há `X-API-Key`, `INTEGRATION_API_TOKEN` ou segredo compartilhado;
- IAM autoriza o `loto-bot` a invocar somente esta função;
- a função lê somente o segredo OAuth indicado por `GmailOAuthSecretArn`;
- o acesso da Lambda ao Secrets Manager e à API do Gmail sai por IPv6; `AWS_USE_DUALSTACK_ENDPOINT=true` seleciona endpoints AWS dual-stack e não há NAT IPv4 nessa arquitetura.

## Pré-requisitos

- AWS CLI e SAM CLI;
- Python 3.12;
- projeto OAuth do Google/Gmail configurado;
- refresh token válido obtido em ambiente local;
- identidade AWS com acesso a CloudFormation, Lambda, IAM, Logs, S3 e Secrets Manager;
- `$VpcId` e `$SubnetId` obtidos nas etapas de criação da rede do [`loto-bot`](../../../loto-bot/docs/AWS_FREE_TIER_MIGRATION_WITH_PROXY_SOCKS5_STEP_BY_STEP.md);
- subnet dual-stack com rota `::/0` e DNS da VPC habilitado;
- mesma conta e região usadas pelo `loto-bot`, salvo configuração cross-account explícita.

```powershell
$AppName = "loto-bot"
$AwsProfile = "<perfil>"
$AwsRegion = "us-east-1"
$StackName = "gmail-reader"
$VpcId = aws ec2 describe-vpcs `
    --filters "Name=tag:Name,Values=$AppName" `
              "Name=tag:Application,Values=$AppName" `
    --query "Vpcs[0].VpcId" `
    --region $AwsRegion `
    --profile $AwsProfile `
    --output text
$AvailabilityZone = aws ec2 describe-availability-zones `
  --filters "Name=state,Values=available" `
  --query "AvailabilityZones[0].ZoneName" `
  --region $AwsRegion `
  --profile $AwsProfile `
  --output text
$SubnetId = aws ec2 describe-subnets `
    --filters "Name=vpc-id,Values=$VpcId" `
              "Name=availability-zone,Values=$AvailabilityZone" `
              "Name=tag:Name,Values=$AppName" `
              "Name=tag:Application,Values=$AppName" `
    --query "Subnets[0].SubnetId" `
    --region $AwsRegion `
    --profile $AwsProfile `
    --output text
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
    VpcId=$VpcId `
    SubnetId=$SubnetId `
    GmailOAuthSecretArn=$GmailOAuthSecretArn `
    WaitTimeoutSeconds=15
```

O timeout solicitado pelo consumidor deve permanecer entre 0 e 15 segundos. A Lambda tem timeout total de 25 segundos.

Confirme antes do deploy que a subnet pertence à VPC compartilhada e possui IPv6:

```powershell
aws ec2 describe-subnets --subnet-ids $SubnetId `
  --query "Subnets[0].{VpcId:VpcId,Ipv4:CidrBlock,Ipv6:Ipv6CidrBlockAssociationSet[0].Ipv6CidrBlock}" `
  --output table --region $AwsRegion --profile $AwsProfile
```

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

Rotacione o refresh token atualizando o mesmo segredo. Para código ou infraestrutura, rode testes, `sam build` e `sam deploy`; para rollback, reaplique uma revisão anterior. O log group mantém 14 dias de logs.

## Checklist

- [ ] Refresh token válido armazenado somente no Secrets Manager.
- [ ] Testes, `sam validate` e `sam build` aprovados.
- [ ] Nenhum evento API Gateway ou Function URL configurado.
- [ ] `VpcId` e `SubnetId` são os mesmos usados pelo `loto-bot`.
- [ ] Subnet dual-stack possui rota IPv6 e a função está com `Ipv6AllowedForDualStack`.
- [ ] Output `FunctionArn` entregue ao `loto-bot`.
- [ ] Role do consumidor limitada a este ARN.
- [ ] Role da função limitada ao segredo OAuth.
- [ ] Nenhuma chave de API compartilhada configurada.
- [ ] Alarmes, logs e orçamento revisados.
