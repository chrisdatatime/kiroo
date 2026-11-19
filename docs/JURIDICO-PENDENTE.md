# Pendências jurídicas e documentais (uso interno — não publicar)

Marcadores visíveis removidos de `src/studio/web/static/termos.html` e `privacidade.html`. O texto das cláusulas foi mantido como estava. Os textos ainda não passaram por revisão jurídica, e a verificação dos contratos dos fornecedores não foi concluída. "Linha" = linha de origem antes da remoção.

## termos.html

| Linha | Trecho / onde estava | O que confirmar |
|---|---|---|
| 128 | Tabela de cobrança, "Preço" ("valor final cobrado de você, impostos inclusos"): `CONFIRMAR COM A CONTABILIDADE` | Com a contabilidade, se o preço exibido de fato inclui os impostos. |
| 158 | Direito de arrependimento (art. 49 do CDC), reembolso integral mesmo com créditos usados: `REVISAR COM O ADVOGADO — regra comercial proposta…` | Reembolso: se a regra comercial proposta (reembolso integral independentemente do consumo dos créditos) é adequada e como o saldo é cancelado. |
| 174 | **Sozinho** (parágrafo após a lista de arquivos guardados por 60 dias): `licença, titularidade e limites do conteúdo gerado por IA` | Licença, titularidade e limites do conteúdo gerado por IA. A seção não tem cláusula sobre isso; precisa ser redigida. |
| 203 | **Sozinho** (parágrafo após a lista de suspensão e encerramento): `regras comerciais propostas de suspensão e encerramento…` | Suspensão e encerramento: ciclo de assinatura já pago e saldo quando o próprio usuário encerra a conta. |
| 211 | Lei aplicável e foro (comarca de São Paulo/SP, foro do domicílio do consumidor): `foro da sede e foro do consumidor` | Foro da sede e foro do consumidor. |

## privacidade.html

| Linha | Trecho / onde estava | O que confirmar |
|---|---|---|
| 110 | Tabela de dados, CPF/CNPJ e cobrança, "Prazo legal fiscal": `confirmar os prazos legais de guarda fiscal e contábil` | Prazos legais de guarda fiscal e contábil. |
| 112 | Tabela de dados, registro do bônus de boas-vindas (hashes), base "Legítimo interesse": `prazo e base legal do registro antifraude` | Prazo de retenção e base legal do registro antifraude. |
| 140 | **Sozinho** (após a tabela de fornecedores): `PENDENTE DE VERIFICAÇÃO DOCUMENTAL DOS FORNECEDORES — confirmar o país e a região de processamento…` | Verificação documental: país e região de processamento de cada fornecedor e política de uso de dados dos contratos. |
| 146 | Quadro "Transferência internacional", após "a verificação dos contratos… ainda não foi concluída": `PENDENTE DE VERIFICAÇÃO DOCUMENTAL DOS FORNECEDORES` | Mesma verificação documental dos contratos dos fornecedores. |
| 146 | Mesmo parágrafo: `base legal da transferência internacional` | Base legal da transferência internacional (art. 33 da LGPD, Resolução CD/ANPD nº 19/2024, cláusulas-padrão contratuais). |
| 175 | **Sozinho** (após a lista de exclusão, backups e retenção): `prazos legais de guarda e regras de backup` | Prazos legais de guarda e regras de backup (rotação de 30 dias, registros de acesso por 6 meses). |

Total: 11 marcadores (5 em termos, 6 em privacidade); 4 estavam sozinhos (termos 174 e 203, privacidade 140 e 175).

---

## Promessas públicas a confirmar

Trechos públicos que afirmam algo operacional ainda não ativo ou não comprovado. Linhas são as **atuais** dos arquivos (depois da remoção dos marcadores; a tabela acima usa as linhas de origem). "Código" = o que o código do repositório faz hoje; não significa que esteja ligado ou testado em produção. Nenhum arquivo público foi alterado para esta seção.

### (a) Retenção de mídia por 60 dias e aviso por e-mail

Código: implementado em `src/studio/compliance.py` (`run_retention`: aviso 7 dias antes, uma vez por produção, e apagamento aos 60 dias; metadados ficam) e chamado a cada 6 h por `_retention_loop` em `src/studio/web/server.py`, **só com `STUDIO_RETENTION_ENABLED=true`. O padrão é desligado, e hoje está desligado.** Com a variável desligada nada é avisado nem apagado. Testado só com dados descartáveis; não rodou em produção. O aviso depende também de o envio de e-mail funcionar.

| Arquivo:linha | Texto | Cumpre hoje? |
|---|---|---|
| privacidade:89 | "Apagamos seus arquivos 60 dias depois, com aviso por e-mail 7 dias antes." | **Não**, enquanto a variável estiver desligada. |
| privacidade:107, 108 | "60 dias; depois os arquivos são apagados, com aviso por e-mail 7 dias antes" | **Não** (idem). |
| privacidade:169 | "…apagados 60 dias depois. Avisamos por e-mail 7 dias antes, com um link para a lista de produções…" | **Não** (idem). |
| termos:172 | "Guardamos os arquivos por 60 dias e depois os apagamos, com aviso por e-mail antes" | **Não** (idem). |
| privacidade:111, 171 e termos:114 | Registro de acesso (IP, data, navegador) "por 6 meses" | **Parcial.** O registro é gravado, mas só é apagado aos 6 meses pela mesma rotina (desligada); hoje ficaria guardado por mais tempo. |

### (b) Contabilizei e CPF/CNPJ

Código: o CPF/CNPJ é validado e guardado em `users.tax_doc` (Minha conta) e entra no export da conta. **Não há nenhuma integração com a Contabilizei nem emissão de NFS-e no código**, e o CPF/CNPJ não é enviado à Stripe nem a ninguém. Se a NFS-e é emitida e se a Contabilizei recebe o dado, isso é processo manual fora do código, que não pude comprovar.

| Arquivo:linha | Texto | Cumpre hoje? |
|---|---|---|
| privacidade:137 | Contabilizei, Brasil: "Dados de cobrança, valor e CPF ou CNPJ quando informado" para "Contabilidade e emissão de NFS-e" | **Não comprovado.** Nenhum código envia o dado; depende de processo manual. |
| privacidade:110, 120 | "Emitir a nota fiscal (NFS-e)"; "constar como tomador na nota fiscal (NFS-e)… nunca o usamos para outra finalidade" | Emissão **não comprovada** (fora do código). A guarda e a finalidade única o código cumpre. |
| termos:129 | "Emitimos NFS-e para as cobranças efetivamente realizadas." | **Não comprovado** (idem). |

### (c) Transferência internacional e lista de fornecedores

Código: não há mecanismo de cláusulas-padrão nem registro de contratos; o texto já diz que a verificação documental não foi concluída.

| Arquivo:linha | Texto | Cumpre hoje? |
|---|---|---|
| privacidade:145 | "o Kiroo adota os mecanismos do art. 33 da LGPD e da Resolução CD/ANPD nº 19/2024, priorizando as cláusulas-padrão contratuais brasileiras" | **Não comprovado.** Nada no repositório mostra cláusulas assinadas. O trecho seguinte do próprio texto admite que a verificação não foi concluída. |
| privacidade:128–137 | Lista de fornecedores e países (fal.ai, OpenRouter, ElevenLabs, Google Gemini, Google login, Stripe, Resend, Cloudflare, Railway, Contabilizei) | **Países e dados recebidos não verificados contra contratos.** Pontos do código: o chat pode usar a **Anthropic** (`STUDIO_CHAT_PROVIDER=anthropic`, em `src/studio/agent_chat.py`), que **não está na lista**; OpenRouter e ElevenLabs aparecem como "acionados dentro do fluxo da fal.ai", o que não confirmei; Railway é a hospedagem indicada pelo `Dockerfile` e por `docs/RAILWAY.md`; o backup vai para o R2 da Cloudflare. |
| privacidade:88, 124 | "Cada um recebe apenas o necessário para a sua função" | **Não comprovado** por auditoria dos dados enviados a cada fornecedor. |
| termos:170 | "Não usamos o seu conteúdo para treinar modelos próprios." | O código não treina modelos; sem contrato de fornecedor para confirmar a política deles. |
| privacidade:131 | Gemini recebe mensagens do chat "quando o chat com IA está ligado" | Coerente: há o kill switch `STUDIO_CHAT_ENABLED`. |
| privacidade:109 | "Não guardamos o texto das mensagens; só a contagem e o custo" | **Cumpre** (`chat_log` guarda só tokens e custo). |

### (d) Exclusão de conta em até 30 dias

Código: `privacy.delete_account` apaga **na hora** o usuário, produções, arquivos e conversas, grava a lápide e anonimiza os pagamentos. O prazo de 30 dias é cumprido (a exclusão é imediata). Exceções que o texto cobre com "dados elegíveis" e "o que guardamos mesmo assim": registro de acesso (6 meses, só some com a retenção ligada), livro de créditos sem vínculo com a pessoa e registro do bônus por hash.

| Arquivo:linha | Texto | Cumpre hoje? |
|---|---|---|
| privacidade:106 | "apagados em até 30 dias depois da exclusão" | **Sim** no banco; cópias de backup, ver (e). |
| privacidade:170 | "Exclusão da conta: apagamos os dados elegíveis em até 30 dias depois do pedido." | **Sim**, imediato. |
| privacidade:163 | "Em Configurações, você também pode exportar os seus dados e excluir a sua conta." | **Sim**: `/api/account/export` e a exclusão existem (Configurações). |
| privacidade:163 | "Respondemos em até 15 dias corridos" (privacidade@kiroo.io) | Processo humano; o código não controla. |

### (e) Outros prazos e garantias

| Arquivo:linha | Texto | Cumpre hoje? |
|---|---|---|
| privacidade:172 | Backups: "a rotação é de no máximo 30 dias… reaplicamos as exclusões já feitas" | **Não comprovado.** Está implementado (banco: 168 h no Litestream; mídia: `archive/` por 30 dias; `restore reapply-deletions`), mas `docs/BACKUP.md` diz que nada foi executado contra o R2 real nem contra o volume real. O backup diário da mídia precisa de um agendador fora do app. |
| privacidade:177 | "conexão criptografada (HTTPS)… Em caso de incidente relevante, avisamos você e a ANPD" | HSTS existe no servidor; **não há procedimento de incidente no repositório.** |
| privacidade:185–187 | Cookies: sessão "Até 30 dias", login Google "10 minutos", `kiroo_dev` "2 anos" | Sessão (30 dias) e login Google (10 min) **cumprem**. A duração de 2 anos do `kiroo_dev` **não confirmei no código** (é gravado pelo frontend). |
| privacidade:181 | "Não usamos cookies de publicidade nem ferramentas de análise ou de rastreamento de terceiros; as fontes são carregadas dos nossos próprios servidores" | A página não carrega recursos externos (testado). O Cloudflare Turnstile (listado) é carregado no cadastro e no login. |
| termos:111, privacidade:196 | "pelo menos 18 anos"; "se identificarmos uma conta de menor, ela será encerrada" | **Só o aceite dos Termos.** Não há verificação de idade nem rotina de encerramento no código. |
| termos:90, 125, 154 | "Se der erro técnico, os créditos voltam" / "devolvidos automaticamente" | **Sim** no código (reserva devolvida como `refund` ao mesmo lote). |
| termos:91, 143–148 | Créditos do plano valem até o fim do ciclo; avulsos não expiram; consumo bônus → plano → avulso | **Sim** (`src/studio/credits.py`). |
| termos:124 | "Bônus de boas-vindas 20 créditos, uma vez por e-mail confirmado" | **Sim**, e há limite extra por dispositivo/IP (`welcome.py`). |
| termos:134, 135 | "geração prioritária na fila"; "suporte por e-mail com prioridade… sem prazo garantido"; "acesso antecipado" no Estúdio | Fila prioritária **sim** (`plans.py`, só no motor fal.ai com produções esperando vaga). Suporte e acesso antecipado são processos humanos. |
| termos:126, 127, 160 | Cobrança "recorrente pela Stripe"; reembolso "pelo mesmo meio de pagamento, por meio da Stripe" | Código da Stripe existe (`payments_stripe.py`). **Não verifiquei se está ligado em produção com chave real.** O reembolso é manual e depende de pedido por e-mail. |
| termos:158 | Desistência em 7 dias com "valor integral… e o saldo que restar é cancelado" | Não há fluxo automático; é manual e depende do processo de suporte. |
| termos:199 | Encerramento pelo Kiroo: "devolvemos o valor dos créditos avulsos… não usados" | Registro em `account_closures` existe; o reembolso é manual. |
| termos:105 | "A cada aceite guardamos a versão do texto, a data e a hora, o endereço IP e o navegador" | **Sim** (`terms_acceptances`, imutável). |
| termos:215, 216, privacidade:210, 211 | Histórico de versões: "Versão candidata, em revisão jurídica" / "Versão inicial, em revisão jurídica" | Texto público que informa revisão em andamento; confirme se continua verdadeiro ao publicar. |
