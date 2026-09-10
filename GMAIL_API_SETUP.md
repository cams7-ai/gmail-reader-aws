# Como habilitar a Gmail API

Guia passo a passo para configurar a Gmail API no Google Cloud Console e executar a aplicação **Gmail Reader**.

---

## Pré-requisitos

- Conta Google (Gmail)
- Python 3.12+
- Dependências instaladas:

  ```powershell
  python -m pip install -e ".[dev]"
  ```

---

## Passo 1 — Acessar o Google Cloud Console

1. Acesse [console.cloud.google.com](https://console.cloud.google.com/)
2. Faça login com sua conta Google

---

## Passo 2 — Criar um Projeto

1. No topo da página, clique em **"Selecionar projeto"**
2. Clique em **"Novo projeto"**
3. Preencha o nome (ex: `gmail-reader`) e clique em **"Criar"**
4. Aguarde a criação e selecione o projeto recém-criado

---

## Passo 3 — Ativar a Gmail API

1. No menu lateral, clique em **"APIs e Serviços" → "Biblioteca"**
2. Na barra de pesquisa, digite **`Gmail API`**
3. Clique no resultado **Gmail API**
4. Clique em **"Ativar"**

---

## Passo 4 — Configurar a Tela de Consentimento OAuth

1. No menu lateral, vá em **"APIs e Serviços" → "Tela de consentimento OAuth"**
2. Selecione o tipo de usuário **"Externo"** e clique em **"Criar"**
3. Preencha os campos obrigatórios:

   | Campo | Valor |
   |---|---|
   | Nome do app | `Gmail Reader` |
   | E-mail de suporte ao usuário | seu e-mail |
   | E-mail do desenvolvedor | seu e-mail |

4. Clique em **"Salvar e continuar"** nas próximas telas
5. Conclua o assistente clicando em **"Voltar ao painel"**

---

## Passo 5 — Adicionar Usuários de Teste

> ⚠️ Enquanto o app não for verificado pelo Google, **apenas e-mails adicionados aqui** poderão fazer login.

1. Na tela de consentimento OAuth, role até **"Usuários de teste"**
2. Clique em **"+ Add Users"**
3. Adicione o e-mail da conta Gmail que será usada
4. Clique em **"Salvar"**

---

## Passo 6 — Criar as Credenciais OAuth 2.0

1. Vá em **"APIs e Serviços" → "Credenciais"**
2. Clique em **"+ Criar credenciais" → "ID do cliente OAuth"**
3. Em **"Tipo de aplicativo"**, selecione **"App para computador"** (Desktop app)
4. Dê um nome e clique em **"Criar"**
5. Clique em **"Baixar JSON"**.
6. Renomeie o arquivo para **`credentials.json`** e coloque na pasta do projeto:

   ```text
   gmail-reader-aws/
   |-- GmailAPI/
   |   `-- credentials.json
   |-- src/
   |   `-- requirements.txt
   `-- template.yaml
   ```

---

## Passo 7 — Gerar o token local

```powershell
$env:PYTHONPATH = "src"
python -c "from config import Settings; from infra import GmailAuthenticator; GmailAuthenticator(Settings()).authenticate()"
```

### O que acontece na primeira execução:
1. O navegador abrirá solicitando login no Google
2. Selecione a conta adicionada como **Usuário de Teste**
3. Se aparecer aviso *"App não verificado"*, clique em **"Avançado" → "Acessar Gmail Reader (não seguro)"**
4. Autorize o acesso
5. O arquivo `token.json` será gerado — **nas próximas execuções o login não é necessário**

---

## Solução de problemas

### Erro 403: `access_denied`
O e-mail utilizado não está na lista de usuários de teste.

**Solução:** Adicione em **"Tela de consentimento OAuth" → "Usuários de teste"** (Passo 5).  
Depois remova `GmailAPI/token.json` e execute novamente:

```powershell
# Windows (PowerShell)
Remove-Item GmailAPI/token.json -ErrorAction SilentlyContinue
$env:PYTHONPATH = "src"
python -c "from config import Settings; from infra import GmailAuthenticator; GmailAuthenticator(Settings()).authenticate()"
```

---

### `FileNotFoundError`: `credentials.json` não encontrado

**Solução:** certifique-se de que o arquivo está em
`GmailAPI/credentials.json`, conforme o passo 6.

---

### Token expirado ou inválido
**Solução:** Delete o `token.json` e refaça o login:

```powershell
Remove-Item GmailAPI/token.json
$env:PYTHONPATH = "src"
python -c "from config import Settings; from infra import GmailAuthenticator; GmailAuthenticator(Settings()).authenticate()"
```

---

## Segurança

Nunca compartilhe os arquivos abaixo — eles contêm acesso à sua conta Google:

- `credentials.json`
- `token.json`

Se usar **Git**, adicione ao `.gitignore`:

```gitignore
GmailAPI/
```

---

## Referências

- [Gmail API — Documentação oficial](https://developers.google.com/gmail/api/guides)
- [Google Cloud Console](https://console.cloud.google.com/)
- [OAuth 2.0 para apps desktop](https://developers.google.com/identity/protocols/oauth2/native-app)
