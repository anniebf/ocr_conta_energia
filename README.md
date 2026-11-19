# BF OCR — Automação de Faturas Energisa

Automação que **baixa as faturas de energia da Energisa**, **identifica o modelo de cada fatura com YOLOv8**, **extrai os dados por coordenadas (OCR)**, gera **XML por unidade consumidora (UC)** e entrega o resultado para a **API de destino** e para a **pasta de rede**.

O projeto tem **duas etapas independentes**, executadas em sequência:

| Etapa | O que faz | Arquivo principal | Onde roda |
|---|---|---|---|
| **1. Download** | Login na Energisa (com código MFA por e-mail), baixa os PDFs do mês e envia para o SMB | `src/main/api/baixar_faturas.py` | Container Docker |
| **2. OCR → XML** | Detecta o modelo da fatura (YOLO), extrai os dados, gera XML, envia para a API e para o SMB | `src/main/coord_text/Faturas_retornando_XML/yolo_pdf_xml_linux.py` | Python no servidor |

A **pasta de PDFs** é a ligação entre as duas etapas: a etapa 1 grava e a etapa 2 lê.

---

## Sumário

- [Arquitetura](#arquitetura)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Etapa 1 — Download das faturas](#etapa-1--download-das-faturas)
- [Etapa 2 — OCR e geração de XML](#etapa-2--ocr-e-geração-de-xml)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Agendamento (Airflow)](#agendamento-airflow)
- [Testes e validação](#testes-e-validação)
- [Troubleshooting](#troubleshooting)
- [Pontos de atenção / melhorias](#pontos-de-atenção--melhorias)
- [Contato](#contato)

---

## Arquitetura

```
                 ┌──────────────────────────────────────────────┐
                 │  ETAPA 1 — baixar_faturas.py (Docker)        │
                 │  1. Calcula período (até dia 9 = mês anterior)│
                 │  2. Login Energisa + código MFA (MS Graph)   │
                 │  3. Lista UCs ativas e baixa os PDFs         │
                 │  4. Envia PDFs ao SMB e limpa > 60 dias      │
                 │  5. Alerta por e-mail (SMTP) se houver falha │
                 └───────────────────────┬──────────────────────┘
                                         │ PDFs
                                         ▼
                        /python_bf/api_energisa/faturas/
                                         │
                                         ▼
                 ┌──────────────────────────────────────────────┐
                 │  ETAPA 2 — yolo_pdf_xml_linux.py             │
                 │  Fase 1: YOLOv8 classifica o modelo          │
                 │          ("fino" ou "refaturado") + cache    │
                 │  Fase 2: extrai texto por coordenadas        │
                 │          (regioes_pdf.py) com pdfplumber     │
                 │          valida CNPJ no Oracle               │
                 │          remove duplicadas, gera XML por UC  │
                 │  Envio:  POST do XML na API (Basic Auth)     │
                 │          PDFs para o SMB                     │
                 └───────────────────────┬──────────────────────┘
                                         │
                 ┌───────────────────────┼──────────────────────┐
                 ▼                       ▼                      ▼
   /python_bf/yolo_xml/xml/       API (URL_BASE)      \\faturaenergia\RPAENERGIA
```

---

## Estrutura do projeto

```
ocr_conta_energia/
├── src/
│   ├── main/
│   │   ├── api/                               # ⭐ ETAPA 1 — Download
│   │   │   ├── baixar_faturas.py              # Script principal (usado no Docker)
│   │   │   ├── email_uc.py                    # Alerta por e-mail (SMTP)
│   │   │   ├── Dockerfile                     # Imagem hiannyurt/energisa-download-faturas
│   │   │   ├── compose.yaml                   # Execução via docker compose
│   │   │   ├── requirements.txt               # Dependências da etapa 1
│   │   │   ├── .env.example                   # Modelo de variáveis de ambiente
│   │   │   └── Download_faturas*.py           # Versões antigas (legado)
│   │   │
│   │   └── coord_text/Faturas_retornando_XML/ # ⭐ ETAPA 2 — OCR → XML
│   │       ├── yolo_pdf_xml_linux.py          # Script principal (servidor Linux)
│   │       ├── yolo_pdf_xml.py                # Mesma lógica com caminhos Windows (dev)
│   │       ├── regioes_pdf.py                 # Coordenadas por modelo (fino/refaturado)
│   │       ├── database/connect_oracle.py     # Validação de CNPJ no Oracle
│   │       ├── diagnostico_yolo.py            # Diagnóstico das classes do YOLO
│   │       └── README_DETECCAO_FINO.md        # Notas sobre a detecção do modelo "fino"
│   │
│   └── runs/detect/yolov8_notas17/            # Modelo YOLOv8 treinado
│       └── weights/best.pt                    # Pesos usados em produção
│
├── requirements.txt                           # Dependências da etapa 2
└── README.md
```

---

## Etapa 1 — Download das faturas

### Como funciona

1. **Período:** até o dia 9 baixa as faturas do mês anterior; a partir do dia 10, as do mês atual.
2. **Limpeza local:** remove de `faturas/` os PDFs de outros períodos.
3. **Login:** autentica com o CNPJ (`ENERGISA_DOCUMENTO`) e solicita o código de segurança.
4. **Código MFA:** lê o e-mail com o código pela **Microsoft Graph API** (MSAL, client credentials).
5. **Download:** lista as UCs ativas e baixa os PDFs em paralelo (`DOWNLOAD_THREADS`), com novas tentativas (`DOWNLOAD_TENTATIVAS`).
6. **SMB:** envia os PDFs para `\\SMB_SERVER\SMB_SHARE` e apaga os arquivos com mais de `SMB_RETENCAO_DIAS` dias.
7. **Alerta:** se alguma UC falhar, envia e-mail via SMTP.

Padrão de nome dos arquivos: `Data_AAAA-MM_UC_<numero>.pdf`

> **Erro 412** no log significa que a fatura do período **ainda não foi emitida** para aquela UC. Não é falha do robô.

### Docker

A imagem usa Python 3.12-slim com fuso `America/Cuiaba` (necessário para a regra do dia 10), roda como **usuário não-root (UID 1001)** e **executa uma vez e termina**. Não expõe porta.

**Build e publicação (máquina de desenvolvimento):**
```bash
cd src/main/api
docker build -t hiannyurt/energisa-download-faturas:latest .
docker push hiannyurt/energisa-download-faturas:latest
```

**Preparar o servidor (uma vez):**
```bash
mkdir -p /python_bf/api_energisa/{logs,faturas}
chown -R 1001:1001 /python_bf/api_energisa/logs /python_bf/api_energisa/faturas
```

**Executar:**
```bash
sudo docker run --rm \
  --add-host faturaenergia:10.194.0.61 \
  --env-file /python_bf/api_energisa/.env \
  -v /python_bf/api_energisa/logs:/app/logs:z \
  -v /python_bf/api_energisa/faturas:/app/faturas:z \
  hiannyurt/energisa-download-faturas:latest
```

| Opção | Motivo |
|---|---|
| `--rm` | O container é descartado ao terminar |
| `--add-host` | `faturaenergia` existe só no `/etc/hosts` do servidor, e o container não herda esse arquivo |
| `--env-file` | As credenciais ficam fora da imagem |
| `:z` nos volumes | Necessário com **SELinux** ativo (Oracle Linux) |
| sem `-p` / sem `--restart` | Não é API; com `--restart` o robô entraria em loop |

### Logs
`/python_bf/api_energisa/logs/AAAA-MM-DD_downloads_faturas_energisa.log`

---

## Etapa 2 — OCR e geração de XML

### Como funciona

**Fase 1: detecção do modelo (YOLOv8)**
- Converte a 1ª página de cada PDF em imagem (PyMuPDF, 200 DPI), em memória.
- O modelo `best.pt` classifica a fatura como **`fino`** ou **`refaturado`**.
- Quando não há detecção, assume `fino` como padrão.
- O resultado fica em cache em `runs/cache_deteccoes.csv`, para não reprocessar o mesmo PDF.

**Fase 2: extração por coordenadas**
- Para cada PDF, usa as regiões do modelo detectado (`regioes_pdf.py`) e extrai o texto com **pdfplumber**.

| Região | Dados extraídos |
|---|---|
| `mais_a_cima` | Informações gerais do cabeçalho |
| `roteiro_tensao` | Roteiro, matrícula, classificação |
| `nota_fiscal_protocolo` | NF, série, protocolo |
| `nome_endereco` | Nome e endereço do cliente |
| `codigo_cliente` | Código da UC |
| `ref_total_pagar` | Mês de referência e total |
| `tributos` | PIS, COFINS, ICMS |
| `tabela_itens` | Energia, demanda, encargos |
| `cnpj` | CNPJ (validado no **Oracle**) |

- Normaliza valores no formato brasileiro e contábil: `1.234,56 → 1234.56` e `(1.234,56) → -1234.56`.
- Ignora itens que não são consumo, listados em `ITENS_A_EXCLUIR_DO_CONSUMO` (compensações, iluminação pública, atualização monetária etc.).
- Remove faturas duplicadas e gera **um XML por UC** (`dicttoxml`).

**Envio**
1. **API:** `POST` de cada XML em `URL_BASE`, com Basic Auth e header `tenantId`.
2. **SMB:** copia os PDFs para `\\SMB_SERVER\SMB_SHARE`.

### Pastas no servidor

| Conteúdo | Caminho |
|---|---|
| PDFs (entrada) | `/python_bf/api_energisa/faturas/` |
| Modelo YOLO | `/python_bf/yolo_xml/runs/detect/yolov8_notas17/weights/best.pt` |
| XMLs (saída) | `/python_bf/yolo_xml/xml/` (é limpa a cada execução) |
| Cache de detecção | `/python_bf/yolo_xml/runs/cache_deteccoes.csv` |

### Executar
```bash
cd /python_bf/yolo_xml
source .venv/bin/activate
python yolo_pdf_xml_linux.py
```

### Exemplo de XML gerado
```xml
<?xml version="1.0" encoding="UTF-8"?>
<fatura>
  <cabecalho>
    <numero_nf>020.537.640</numero_nf>
    <cnpj_consumidor>XX.XXX.XXX/XXXX-XX</cnpj_consumidor>
    <nome_cliente>CLIENTE EXEMPLO</nome_cliente>
    <matricula>3359145-4</matricula>
    <total_pagar>1234.56</total_pagar>
  </cabecalho>
  <itens>
    <item>
      <descricao>ENERGIA ATIVA</descricao>
      <quantidade>100</quantidade>
      <valor>1234.56</valor>
    </item>
  </itens>
  <tributos>
    <icms>180.45</icms>
    <pis_confins>50.32</pis_confins>
  </tributos>
</fatura>
```

---

## Variáveis de ambiente

> ⚠️ **Formato do `.env` para Docker (`--env-file`):** `CHAVE=valor`, **sem espaços** ao redor do `=`, **sem aspas**, **sem comentário na mesma linha** e com **final de linha Unix (LF)**. O `python-dotenv` aceita esses formatos, o Docker não.

### Etapa 1 — `/python_bf/api_energisa/.env` (modelo em `src/main/api/.env.example`)

| Grupo | Variáveis |
|---|---|
| Microsoft Graph (leitura do código MFA) | `GRAPH_CLIENT_ID`, `GRAPH_TENANT_ID`, `GRAPH_CLIENT_SECRET`, `BOT_USER_EMAIL`, `BOT_EMAIL_FOLDER`, `BOT_EMAIL_SUBJECT` |
| Energisa | `ENERGISA_DOCUMENTO`, `ENERGISA_EMAIL_CODIGO_PREFIXO`, `ENERGISA_EMAIL_CODIGO_DOMINIO` |
| Execução | `DOWNLOAD_THREADS`, `DOWNLOAD_TENTATIVAS`, `CODIGO_TIMEOUT_S`, `CODIGO_ESPERA_INICIAL_S` |
| Pasta de rede | `ENVIAR_SMB`, `SMB_SERVER`, `SMB_SHARE`, `SMB_USER`, `SMB_PASSWORD`, `SMB_RETENCAO_DIAS`, `SMB_LIMPEZA_PADRAO` |
| Alerta por e-mail | `server_smtp`, `port`, `sender_mail`, `password`, `destinatario_email` |

### Etapa 2 — `.env` em `/python_bf/yolo_xml/`

| Grupo | Variáveis |
|---|---|
| Pasta de rede | `SMB_SERVER`, `SMB_SHARE`, `SMB_USER`, `SMB_PASSWORD` |
| API de destino | `URL_BASE`, `USER_BASE`, `PASS_BASE`, `TENANT_ID` |
| Oracle | `usernameBd`, `passwordBd`, `dsn` |

---

## Agendamento (Airflow)

DAG **`Download_Faturas_Energia`**, task `executar_automacao_energisa`.

A forma recomendada é chamar o Docker com um **`BashOperator`**. Se o container sair com código diferente de 0, a task é marcada como FAILED:

```python
from airflow.operators.bash import BashOperator

executar_automacao_energisa = BashOperator(
    task_id="executar_automacao_energisa",
    bash_command=(
        "sudo docker run --rm --add-host faturaenergia:10.194.0.61 "
        "--env-file /python_bf/api_energisa/.env "
        "-v /python_bf/api_energisa/logs:/app/logs:z "
        "-v /python_bf/api_energisa/faturas:/app/faturas:z "
        "hiannyurt/energisa-download-faturas:latest"
    ),
)
```

> Com `PythonVirtualenvOperator`, a função chamada **não pode usar `sys.exit()`**. Se usar, o Airflow falha com `FileNotFoundError: .../script.out`.

---

## Testes e validação

**Conectividade de dentro do container (SMB e SMTP):**
```bash
sudo docker run --rm --add-host faturaenergia:10.194.0.61 --entrypoint python \
  --env-file /python_bf/api_energisa/.env hiannyurt/energisa-download-faturas:latest -c "
import os,socket
for v,pv in [('SMB_SERVER',None),('server_smtp','port')]:
    h=os.environ.get(v); p=int(os.environ.get(pv,'445')) if pv else 445
    print(v,'=',repr(h),'porta',p)
    try: socket.create_connection((h,p),5); print('  OK')
    except Exception as e: print('  FALHOU:',e)
"
```

**Checklist após a execução:**
- [ ] `ls /python_bf/api_energisa/faturas` mostra PDFs `Data_AAAA-MM_UC_*.pdf` do período atual
- [ ] O log do dia termina com `TOTAL: X/Y faturas baixadas`, e as falhas são apenas `412`
- [ ] `ls /python_bf/yolo_xml/xml` mostra um XML por UC
- [ ] A saída da etapa 2 mostra `[SUCESSO]` no POST de cada XML
- [ ] Os arquivos aparecem em `\\faturaenergia\RPAENERGIA`

**Testes unitários sugeridos (pytest) para a etapa 2:**
```python
# test_normalizacao.py
from yolo_pdf_xml_linux import normalizar_valor

def test_valor_brasileiro():
    assert normalizar_valor("1.234,56") == 1234.56

def test_valor_contabil_negativo():
    assert normalizar_valor("(1.234,56)") == -1234.56
```

---

## Troubleshooting

| Erro | Causa | Solução |
|---|---|---|
| `poorly formatted environment: variable 'x ' contains whitespaces` | Espaço antes do `=` no `.env` | Usar `CHAVE=valor` |
| `Tenant '"e96d..."' not found` | Aspas nos valores do `.env` | Remover as aspas |
| `Failed to connect to ' faturaenergia:445'` | Espaço depois do `=`, ou host só no `/etc/hosts` | Limpar o `.env` e usar `--add-host` |
| `Name or service not known` no SMTP | Valor de `server_smtp` com aspas ou espaço | Limpar o `.env` |
| `permission denied ... docker.sock` | Usuário sem acesso ao Docker | Usar `sudo` ou adicionar ao grupo `docker` |
| `Permission denied` ao gravar PDF | Pasta não pertence ao UID 1001, ou SELinux | `chown 1001:1001` e `:z` nos volumes |
| `FileNotFoundError: .../script.out` (Airflow) | `sys.exit()` na função chamada | `BashOperator` ou `raise` no lugar de `sys.exit` |
| `Erro 412` no download | Fatura do período ainda não emitida | Nenhuma ação; aguardar a emissão |

**Limpar o `.env` automaticamente** (remove `\r`, espaços e aspas, com backup em `.env.bak`):
```bash
sudo sed -i.bak -E 's/\r$//; s/^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*/\1=/; s/[[:space:]]+$//; s/^([A-Za-z_][A-Za-z0-9_]*)=["'"'"'](.*)["'"'"']$/\1=\2/' /python_bf/api_energisa/.env
```

---

## Pontos de atenção / melhorias

- **PDFs enviados duas vezes ao SMB:** as etapas 1 e 2 fazem upload dos mesmos PDFs. Uma delas pode deixar de enviar (por exemplo, `ENVIAR_SMB=false` na etapa 1).
- **Efeitos colaterais no import (etapa 2):** o script executa `sudo rm -rf` na pasta de XML, conecta no Oracle e carrega o YOLO já no import. Mover isso para dentro do `main()` facilita os testes e evita apagar arquivos sem querer.
- **Containerizar a etapa 2:** hoje ela roda em uma venv no servidor. Com uma imagem Docker, o deploy das duas etapas ficaria padronizado.
- **Duas versões do mesmo script** (`yolo_pdf_xml.py` e `yolo_pdf_xml_linux.py`): unificar e ler os caminhos de variáveis de ambiente.
- **Coordenadas fixas:** mudanças no layout da Energisa exigem atualizar `regioes_pdf.py` e, possivelmente, retreinar o YOLO.
- **Arquivos legados** (`Download_faturas*.py`, `*_antigo.py`, `*copy.py`): mover para uma pasta `legado/` ou remover.

---

## Contato

**Desenvolvedora:** Hianny Urt — Ramal 8777 — Bom Futuro, Escritório Cuiabá

**Última atualização:** 19 de novembro de 2026
