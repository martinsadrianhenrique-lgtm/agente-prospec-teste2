# Engage Flow — Prospecção e CRM 2.1

Aplicativo Streamlit para Adrian e Vitor trabalharem na mesma base, com acesso individual, autoria dos contatos e acompanhamento comercial.

**Para colocar online, comece por [PUBLICAR_STREAMLIT.md](PUBLICAR_STREAMLIT.md).** O aplicativo precisa de PostgreSQL remoto para os dois usuários compartilharem dados persistentes. O pacote não vem publicado nem conectado a um banco remoto.

## O que esta versão entrega

- Login individual: Adrian como administrador e Vitor como operador. Os acessos iniciais são criados por configuração privada, com opção de troca obrigatória no primeiro login. Senhas e hashes reais não ficam neste repositório público.
- Listas por cidade, nicho ou campanha: criar, renomear, arquivar, restaurar e exportar. Uma empresa participa de várias listas com uma única ficha e histórico.
- Cadastro dentro da lista, tabela editável para digitar/colar contatos, inclusão de contatos do CRM e importação de planilhas para uma lista.
- Pessoa de contato, e-mail e etiquetas editáveis, quadro visual do funil, painel diário e aparência adaptada a telas pequenas.
- CRM com responsável atual, primeiro e último contato realizado por, data, canal e histórico completo. Transferir um lead não altera a autoria dos contatos anteriores.
- Agenda com próximas ações, prazos e tarefas atrasadas. Cada pessoa vê suas tarefas e pode consultar o trabalho da equipe.
- Registro de contatos já realizados por WhatsApp, ligação, e-mail, Instagram, presencial ou outro canal. Nenhuma mensagem é enviada automaticamente.
- Rascunhos revisáveis e links de WhatsApp. Identidade, número comercial, permissão e evidência precisam ser conferidos antes de liberar esses links.
- Importação CSV/TSV/XLSX com mapeamento de colunas. As bases reais ficam fora deste repositório e entram pelo aplicativo autenticado.
- Pesquisa assistida por links para Google/Maps e cadastro manual com fontes. Não faz coleta automática nem integração com a API do Google.
- Exportação CSV e Excel com CRM, histórico, tarefas e evidências; backup completo exclusivo do administrador.

## Rotina dos dois usuários

1. Adrian entra e abre **Listas → Criar nova lista**. Preencha nome, cidade e nicho. Cadastre contatos, cole uma tabela ou importe os arquivos em **Importar**, escolhendo a lista de destino.
2. Adrian atribui leads à equipe. Vitor também pode assumir leads sem responsável em **Leads e CRM**. Os dois podem consultar a base; Vitor edita seus próprios leads.
3. Quem fez o contato registra o conteúdo em **Conversa** usando seu próprio acesso. A autoria é registrada automaticamente.
4. Em **Acompanhamento**, atualize a etapa, o valor e a próxima ação. Reunião e proposta precisam de uma próxima ação com data.
5. Consulte **Hoje** para executar as tarefas. Use **Atualizar dados** para buscar as alterações feitas pela outra pessoa. Não há atualização em tempo real por notificação.
6. No celular, abra o menu lateral no canto superior para navegar. É possível adicionar a URL à tela inicial pelo navegador.
7. Em **Configurações**, Adrian pode criar novos operadores. Cada operador organiza suas próprias listas; o administrador organiza todas. Consultar uma lista não concede edição das fichas atribuídas a outra pessoa.

## Regras do acompanhamento

| Evento | Resultado |
| --- | --- |
| Contato realizado registrado manualmente, lead em Contatado | Se não houver próxima ação informada nem tarefa pendente, cria conferência de retorno em 2 dias úteis. |
| Envio inicial de rascunho marcado como enviado | Cria primeiro follow-up em 2 dias úteis. |
| Primeiro follow-up efetivamente enviado | Cria último follow-up em 5 dias úteis. |
| Último follow-up efetivamente enviado | Cria tarefa de conferir retorno/encerrar em 5 dias úteis. |
| Resposta recebida | Cancela a sequência automática de follow-ups. |
| Reunião, proposta ou evolução da negociação | Interrompe follow-ups genéricos; usa a próxima ação combinada. |
| Recusa/opt-out | Bloqueia nova abordagem e cancela tarefas; o telefone também fica bloqueado em outras fichas. |

Dias úteis desconsideram sábados e domingos, mas não feriados. Datas são exibidas no horário de Brasília. Abrir o WhatsApp não comprova envio: registre o envio somente depois de fazê-lo. O aplicativo não lê respostas do WhatsApp; elas precisam ser registradas no CRM.

## Qualidade dos dados

Dados importados e links de busca genérica não contam como validação. A prioridade fica **A validar** até existirem os cinco critérios verificados com evidências de até 30 dias. Números separados na mesma célula são tratados individualmente. Telefones compartilhados geram aviso, sem fundir empresas diferentes.

A repetição do mesmo arquivo não duplica a carga. A combinação normalizada de empresa, cidade e endereço identifica duplicatas entre arquivos. Alterações relevantes desses campos podem gerar uma nova ficha e exigem revisão manual. Dados já existentes não são sobrescritos pela importação.

## Rodar localmente

Requer Python 3.12. Abra um terminal na pasta que contém `app.py`:

```bash
python -m venv .venv
```

No Windows:

```powershell
.venv\Scripts\Activate.ps1
```

No macOS/Linux:

```bash
source .venv/bin/activate
```

Depois:

```bash
python -m pip install -r requirements.txt
```

Copie o arquivo privado entregue separadamente para `.streamlit/secrets.toml`. Somente para testar no seu computador, altere a seção `[app]` para:

```toml
[app]
mode = "local"
database_url = "sqlite:///data/engage_flow.db"
```

Mantenha as duas seções `bootstrap_users` do arquivo privado e execute:

```bash
python -m streamlit run app.py
```

SQLite fica restrito ao modo local. Para publicação, use PostgreSQL e `mode = "cloud"`.

## Backup e recuperação

Em **Configurações**, Adrian gera e baixa o backup JSON. Ele contém leads, listas, contatos, usuários com hashes de senha, histórico, tarefas e evidências. Não contém sessões de login nem a senha do banco. Guarde-o em local privado. O Excel é um relatório e não substitui o backup completo.

Restaure em um banco novo, antes de iniciar o aplicativo. Configure `PROSPECTOR_DATABASE_URL` no ambiente, apontando para esse banco, e execute:

```bash
python tools/restore_backup.py caminho/do/backup.json
```

Para um SQLite local novo, configure também `PROSPECTOR_MODE=local`. O comando recusa restauração sobre usuários ou leads existentes. As senhas atuais do backup serão preservadas; as senhas iniciais não são reaplicadas.

## Testes

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Consulte [VALIDACAO.md](VALIDACAO.md) para a cobertura e os limites da validação. A atualização de um banco 2.0 desta mesma aplicação para 2.1 é aditiva: cria tabelas de listas e recupera as campanhas existentes como listas, preservando contas e histórico. Faça backup antes da atualização. Aplicativos antigos com outro formato de banco exigem migração específica.

O GitHub Actions executa os testes com SQLite e com um PostgreSQL 16 descartável. Três testes que dependem das bases privadas são pulados no repositório público; os fluxos de listas e interface também são testados com dados sintéticos.
