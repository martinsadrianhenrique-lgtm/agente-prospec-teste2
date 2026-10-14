# Validação — Engage Flow 2.1

Ambiente de referência: Python 3.12, Streamlit 1.65.0, SQLAlchemy 2.0.54, SQLite local com transações e chaves estrangeiras. Dependências fixadas em `requirements.txt`.

## Testes automatizados

A suíte cobre domínio, concorrência e interface pelo `streamlit.testing.v1.AppTest`. Os testes locais incluem as bases privadas; no GitHub, três casos que dependem dessas bases são pulados. O workflow configura execuções separadas em SQLite e PostgreSQL 16 descartável.

| Área | Verificação |
| --- | --- |
| Login | Vitor entra com a senha inicial; troca obrigatória; senha pessoal preservada após reinicialização; sessões antigas encerradas. |
| Controle de acesso | Leitura anônima negada, limite de tentativas, importação e backup restritos ao administrador. |
| Base inicial | 213 empresas; 187 ocorrências de telefone, 185 números distintos; 33 empresas sem telefone; 4 fichas com número compartilhado. |
| Duplicação | Reimportação do mesmo arquivo e da base automotiva em XLSX mantém 213 empresas e preserva histórico. |
| Autoria | Contatos feitos por Adrian e Vitor preservam primeiro/último autor após transferência de responsável. |
| Concorrência | Duas gravações com a mesma versão de uma ficha: uma confirma e a outra recebe conflito, sem sobrescrever silenciosamente. |
| Acompanhamento | Registro manual de contato gera retorno se necessário; segunda interação não duplica a tarefa. |
| WhatsApp | Link não registra envio; envio confirmado é idempotente; sequência segue os prazos; não há disparo automático. |
| Interrupções | Resposta cancela follow-ups; reunião mantém sua etapa; rascunhos antigos não liberam abordagem inválida. |
| Recusa | Bloqueio se aplica à ficha, ao número compartilhado e a uma ficha futura com o mesmo número. |
| Evidências | Desconhecido difere de zero; score exige cinco critérios atuais; evidência vencida não pontua. |
| Recuperação | Backup em banco vazio preserva contas e autoria; restauração sobre base existente é recusada. |
| Exportação | CSV e Excel incluem autoria; textos que parecem fórmulas são neutralizados. |
| Interface | Login, troca de senha, carga inicial, todas as páginas do administrador, geração de backup e acesso independente do Vitor. |
| Listas | Mesma ficha em várias listas, importação para lista, remoção sem apagar histórico, arquivamento, permissões e conflito de edição. |
| Cadastro | Pessoa de contato, e-mail e etiquetas; alterar identidade exige reconferir o canal; senha pessoal configurada aceita login com variação de maiúsculas. |
| Atualização | Campanhas 2.0 convertidas em listas, backup 2.1 restaurado com listas e contatos. |

## Limites desta validação

- O PostgreSQL de produção e a publicação no Streamlit dependem da configuração privada na conta do proprietário. A conectividade, o TLS e a persistência após reinício devem ser conferidos na publicação, conforme o guia. O PostgreSQL do workflow é descartável e não é o banco de produção.
- Os testes de interface executam o aplicativo pelo AppTest. Não houve inspeção visual em um navegador móvel real; a interface usa componentes Streamlit e ajustes de largura para telas pequenas.
- O aplicativo não lê WhatsApp, não confirma entrega de mensagem e não procura empresas automaticamente. O envio, a resposta e as evidências dependem de registros feitos pela equipe.
- O código e o banco da versão anterior não estavam disponíveis. Foram utilizadas as especificações e as duas bases fornecidas; não foi migrado histórico anterior não fornecido.
- Foram testados os dois usuários e a base de 213 empresas; não há ensaio de carga para grandes equipes ou bases extensas.

Para reproduzir os testes, instale `requirements-dev.txt` e execute `python -m pytest -q` na raiz do projeto.
