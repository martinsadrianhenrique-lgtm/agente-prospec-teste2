# Publicar a versão 2.1 para Adrian e Vitor

O resultado será uma única URL HTTPS, acessível no celular e no computador. Cada pessoa entra com seu usuário, e os registros ficam no mesmo PostgreSQL remoto.

## 1. Preparar um banco persistente

Use um projeto PostgreSQL remoto, por exemplo em um serviço compatível com Streamlit como Neon ou Supabase. Copie a string de conexão do banco com TLS/SSL. Use a URL de conexão PostgreSQL, não a URL HTTP do painel ou uma chave de API.

Exemplo de formato, sem credenciais reais:

```text
postgresql://USUARIO:SENHA@HOST/BANCO?sslmode=require
```

Prefira a conexão agrupada/pooler indicada pelo provedor para aplicações web, quando disponível. No Supabase, confira a compatibilidade de rede do endereço de conexão escolhido. O usuário do banco precisa criar e acessar as tabelas `ef_*` em um banco dedicado ao aplicativo.

**O arquivo SQLite local não deve ser usado para guardar o CRM no Streamlit Community Cloud.** Nesta versão, o modo online exige PostgreSQL e interrompe a inicialização se receber uma configuração SQLite.

## 2. Colocar o projeto no GitHub

O repositório deste projeto é [martinsadrianhenrique-lgtm/agente-prospec-teste2](https://github.com/martinsadrianhenrique-lgtm/agente-prospec-teste2), com entrada `app.py` e branch `main`.

Ele é público e recebe somente código, testes sintéticos e documentação. Não envie `Configuracao_Privada_Streamlit.toml`, `.streamlit/secrets.toml`, bases de contatos, bancos locais ou backups. A pasta `initial_data/` está ignorada pelo Git. Importe suas planilhas somente pelo aplicativo autenticado.

Se já existir um aplicativo online, faça backup dos dados antigos e mantenha o aplicativo anterior até validar o novo. Esta V2 não recupera automaticamente o histórico de uma versão cujo código/banco não foi disponibilizado.

## 3. Configurar o Streamlit Community Cloud

1. Entre em [share.streamlit.io](https://share.streamlit.io/) e conecte o repositório autorizado.
2. Crie um aplicativo selecionando o repositório e a branch.
3. Informe `app.py` como arquivo principal e `main` como branch.
4. Nas opções avançadas, selecione Python **3.12**.
5. Em **Secrets**, cole o conteúdo de `Configuracao_Privada_Streamlit.toml`.
6. Troque apenas a URL de exemplo de `app.database_url` pela URL real do PostgreSQL. Mantenha `mode = "cloud"` e as duas seções de usuários.
7. Publique. O aplicativo cria suas tabelas e os dois usuários no primeiro início.

Use a tela de Settings → Secrets para futuras alterações de conexão. Nunca coloque a URL com senha no código do repositório.

## 4. Acessos e primeira carga

| Pessoa | Usuário | Acesso |
| --- | --- | --- |
| Adrian | `adrian` | Administrador: importar, transferir responsáveis, gerenciar Vitor e baixar backup. |
| Vitor | `vitor` | Operador: consultar a equipe, assumir leads livres e trabalhar nos próprios leads. |

As senhas iniciais ficam somente no arquivo privado. O acesso de Adrian aceita `Adrian` ou `adrian` e pode entrar diretamente com a senha escolhida por ele (`must_change_password = false`). Vitor troca a senha inicial no primeiro login. Novas senhas devem ter pelo menos 8 caracteres. Reiniciar ou republicar o aplicativo não redefine senhas existentes.

Entre como Adrian e crie uma lista em **Listas**. Depois abra **Importar**, selecione essa lista e envie o CSV/XLSX. As bases recebidas anteriormente contêm 113 registros de clínicas e 100 automotivos. O CSV e o XLSX automotivo representam a mesma base; basta importar um deles.

## 5. Liberar o acesso nos dois dispositivos

Copie a URL publicada e abra-a no seu computador e no celular do Vitor. Cada pessoa usa seu login individual. Se você restringir também os espectadores nas configurações do Streamlit, inclua as duas contas autorizadas nessa camada de acesso; a conta Streamlit é diferente do usuário interno `vitor`.

No celular, o menu lateral fica recolhido. Use o botão no canto superior para abrir Hoje, Leads e CRM e as outras áreas. O WhatsApp abre no aplicativo/navegador disponível no dispositivo.

## 6. Conferência antes de começar a operação

1. Faça login com Adrian e Vitor em navegadores diferentes; Vitor deve trocar a senha inicial.
2. Carregue as bases; confirme 213 empresas.
3. Atribua um lead a Vitor. Com o login dele, registre um contato real e uma próxima ação.
4. No acesso de Adrian, use **Atualizar dados** e confira o nome de Vitor no histórico e em “Último contato por”.
5. Reinicie o aplicativo e confira que os dados e as senhas atuais continuam disponíveis.
6. Gere o primeiro backup completo e guarde-o em local privado.

## Se algo impedir a abertura

| Mensagem/situação | O que conferir |
| --- | --- |
| Configuração inicial | Se colou as seções `[app]` e os dois usuários em Secrets e substituiu a URL de exemplo. |
| Não foi possível conectar ao banco | Host, senha, nome do banco, TLS, disponibilidade do projeto e endereço/pooler compatível. |
| Senha inicial não funciona depois da troca | Use a senha pessoal atual. Adrian pode redefinir a senha de Vitor em Configurações. |
| Sessão expirada | Entre novamente. As sessões duram até 8 horas; atualizar completamente a página também pode pedir novo login. |
| Não consigo editar um lead | Vitor precisa assumir o lead livre ou receber a transferência de Adrian. |
| Lead atualizado por outra pessoa | Atualize os dados e confira o histórico antes de repetir a edição. |

Se Adrian perder sua senha, execute `python tools/reset_admin.py` em ambiente privado conectado ao banco. A ferramenta pede a nova senha sem mostrá-la e encerra as sessões antigas. Alterar o hash de bootstrap em Secrets não redefine usuários existentes.

Documentação oficial de referência:

- [Organização dos arquivos para publicação](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/file-organization)
- [Gerenciamento de Secrets](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)
- [Conectar Streamlit a PostgreSQL](https://docs.streamlit.io/develop/tutorials/databases/postgresql)
- [Conectar a Neon](https://docs.streamlit.io/develop/tutorials/databases/neon)
- [Conectar a Supabase](https://docs.streamlit.io/develop/tutorials/databases/supabase)
