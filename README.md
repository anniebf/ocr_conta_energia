# BF OCR - Sistema de Automação de Faturas Energisa

## 📋 Visão Geral

Sistema automatizado para download, processamento e **envio de faturas de energia elétrica** da **Energisa** para uma **pasta compartilhada de rede**. O processo inclui extração de dados via OCR, conversão para formato XML e sincronização com servidor SMB do usuário bot.

---

## 🎯 Fluxo Principal

```
Download de PDFs (Energisa) 
        ↓
Extração de Dados via Coordenadas (OCR)
        ↓
Processamento de Informações
        ↓
Geração de XML
        ↓
Envio para Pasta Compartilhada (PRINCIPAL) ⭐
```

---

## 📁 Estrutura do Projeto

```
bf_ocr/
├── src/
│   ├── main/
│   │   ├── api/                          # 📥 Download de faturas
│   │   │   ├── Download_faturas.py      # Automação Energisa
│   │   │   ├── Download_faturas_linux.py
│   │   │   ├── email_uc.py              # Integração com email
│   │   │   ├── job.py                   # Agendamento de tarefas
│   │   │   └── openia_extractor_cabecalho.py
│   │   │
│   │   ├── coord_text/
│   │   │   ├── Faturas_retornando_XML/
│   │   │   │   ├── post_folder_temp_linux.py # ⭐ PRINCIPAL: Envio para pasta compartilhada
│   │   │   │   └── get_text_coord_xml.py    # Processamento para XML
│   │   │   ├── ocr_text/                # Testes de extração OCR
│   │   │   └── text_table_refaturada.py # Teste de tabelas
│   │   │
│   │   └── faturas/                      # Armazenamento de PDFs
│   │
│   └── resource/
│       ├── pdf/                          # PDFs processados
│       ├── xml/                          # XMLs gerados
│       └── pdf_fino/                     # JSONs de dados extraídos
│
├── APRENDIZADO/                          # Testes e exemplos
│   ├── json/                             # JSONs exemplo
│   └── tests/                            # Testes diversos
│
└── logs/                                 # Arquivos de log
```

---

## 🔑 Componentes Principais

### 1️⃣ **post_folder_temp_linux.py** (Principal - Envio para Pasta Compartilhada)
**Localização:** `src/main/coord_text/Faturas_retornando_XML/post_folder_temp_linux.py`

#### Função Principal
**Envia PDFs e XMLs** para uma **pasta compartilhada em rede SMB** do usuário bot via protocolo SMB3:
- Conexão autenticada com servidor SMB
- Upload recursivo de pastas
- Processamento paralelo de múltiplos arquivos
- Tratamento robusto de erros
- Suporte a arquivos grandes (4MB chunks)

#### Tecnologias Utilizadas
- `smbprotocol` - Conexão SMB3 nativa
- `python-dotenv` - Variáveis de ambiente (.env)
- `os.walk()` - Processamento recursivo de pastas

#### Configurações Padrão
```python
host = "192.168.200.20"              # Servidor SMB
user = "bf.bot@bomfuturo.com.br"    # Usuário bot
SHARE_NAME = "temporario$"           # Compartilhamento
REMOTE_DEST_FOLDER = "fatura_energisa_bot"  # Pasta de destino
```

#### Pastas que Envia
1. **PDFs:** `/python_bf/api_energisa/faturas`
2. **XMLs:** `/python_bf/yolo_xml/xml`

#### Saída
- ✅ Arquivos salvos na pasta `\\192.168.200.20\temporario$\fatura_energisa_bot\`
- 📊 Logs de upload no console

#### Exemplo de Uso
```python
from post_folder_temp_linux import enviar_temp

enviar_temp()  # Envia as duas pastas para o servidor compartilhado
```

---

### 2️⃣ **Download_faturas.py** (Etapa 1 - Download)
**Localização:** `src/main/api/Download_faturas.py`

#### Função Principal
Automatiza o **download de faturas** da plataforma da **Energisa** através de:
- Autenticação automática (login com MFA - código de segurança)
- Consulta de unidades consumidoras
- Busca de faturas por período
- Download de PDFs

#### Tecnologias Utilizadas
- `requests` + `curl_cffi` - Requisições HTTP com bypass de segurança
- `msal` - Autenticação Microsoft
- `python-dotenv` - Variáveis de ambiente (.env)
- `logging` - Registro de operações

#### Fluxo de Autenticação
```
1. Obter cookies e token de acesso
   ↓
2. Solicitar código de segurança (MFA)
   ↓
3. Buscar código recebido por email
   ↓
4. Validar código e completar login
   ↓
5. Consultar unidades consumidoras
   ↓
6. Buscar e baixar faturas em PDF
```

#### Saída
- 📄 **PDFs salvos** em `src/main/faturas/` ou `src/resource/pdf/`
- 📊 **Logs de operação** em `./logs/{data}_downloads_faturas_energisa.log`

#### Exemplo de Uso
```python
automacao = EnergisaAutomacao(documento="seu_cpf_cnpj")
if automacao.executar_login_automatico():
    faturas = automacao.buscar_faturas_por_periodo(mes="01", ano="2025")
    # PDFs são automaticamente baixados
```

---

### 3️⃣ **get_text_coord_xml.py** (Etapa 2 - Processamento)
**Localização:** `src/main/coord_text/Faturas_retornando_XML/get_text_coord_xml.py`

#### Função Principal
**Extrai dados dos PDFs** utilizando **coordenadas de regiões** e converte para **XML** (gera saída para envio):
- Leitura de PDFs com `pdfplumber`
- Extração de texto por região (coordenadas x, y)
- Processamento e limpeza de dados
- Validação com banco de dados (CNPJ)
- Conversão final para XML

#### Regiões Definidas
O script mapeia áreas específicas do PDF:

| Região | Descrição | Dados Extraídos |
|--------|-----------|-----------------|
| `mais_a_cima` | Cabeçalho superior | Informações gerais |
| `roteiro_tensao` | Roteiro e tensão | Matricula, classificação |
| `nota_fiscal_protocolo` | Identificação da fatura | NF, série, protocolo |
| `nome_endereco` | Dados do cliente | Nome, endereço |
| `codigo_cliente` | Identificação do cliente | Código UC |
| `ref_total_pagar` | Período e valor total | Referência, total |
| `tributos` | Impostos e contribuições | PIS, CONFINS, ICMS |
| `tabela_itens` | Itens de consumo | Energia, demanda, encargos |
| `cnpj` | Documento da distribuidora | CNPJ |

#### Principais Funções

**1. Extração de Texto**
```python
extrair_texto_nas_coordenadas(pdf_path, retangulo)
# Extrai texto dentro de um retângulo do PDF
```

**2. Processamento de Itens**
```python
processar_tabela_itens(linhas, pdf_path)
# Converte linhas de fatura em estrutura de dados
# Exemplo: "100 KWH  1.234,56" → {'quantidade': '100', 'valor': '1234.56'}
```

**3. Normalização de Valores**
```python
normalizar_valor("1.234,56")  # → 1234.56
normalizar_valor("(1.234,56)") # → -1234.56 (contábil)
```

**4. Processamento de CNPJ**
```python
processar_cnpj(texto, nome_titular)
# Extrai CNPJ e valida no banco de dados Oracle
```

**5. Geração de XML**
```python
dicttoxml(dados_dict)  # Converte dicionário em XML
```

#### Itens Excluídos do Consumo
O script ignora automaticamente:
- COMPENSACAO POR INDICADOR
- ATUALIZAÇÃO MONETARIA
- CONTRIB DE ILUM PUB
- CUSTO DE DISPONIBILIDADE
- SUBSTITUIÇÃO TRIBUTÁRIA
- Entre outros...

#### Estrutura de Saída XML
```xml
<?xml version="1.0" encoding="UTF-8"?>
<fatura>
  <cabecalho>
    <numero_nf>020.537.640</numero_nf>
    <cnpj_consumidor>XX.XXX.XXX/XXXX-XX</cnpj_consumidor>
    <nome_cliente>CLIENTE EXEMPLO</nome_cliente>
    <roteiro>12345</roteiro>
    <matricula>3359145-4</matricula>
    <total_pagar>1234.56</total_pagar>
  </cabecalho>
  <itens>
    <item>
      <descricao>ENERGIA ATIVA</descricao>
      <quantidade>100</quantidade>
      <valor>1234.56</valor>
      <icms>180.45</icms>
    </item>
  </itens>
  <tributos>
    <icms>180.45</icms>
    <pis_confins>50.32</pis_confins>
  </tributos>
</fatura>
```

---

## 🧪 Arquivos de Teste

Além dos três principais, existem testes para validar funcionalidades:

| Arquivo | Propósito |
|---------|-----------|
| `APRENDIZADO/tests/FITZ.py` | Testes com PyMuPDF (FITZ) |
| `APRENDIZADO/tests/pdf_extractors.py` | Teste de extractores de PDF |
| `APRENDIZADO/tests/readers_pdf.py` | Leitores de PDF |
| `APRENDIZADO/tests/regex_pdf.py` | Testes de regex em PDFs |
| `APRENDIZADO/tests/openia_extractor_*.py` | Testes com OpenAI |
| `APRENDIZADO/tests/text_extractor_*.py` | Extractores de texto |

---

## 🚀 Como Usar

### Pré-requisitos
```bash
pip install -r requirements.txt
```

### Dependências Principais
- `pdfplumber` - Extração de texto de PDFs
- `dicttoxml` - Conversão para XML
- `requests` + `curl_cffi` - Requisições HTTP
- `msal` - Autenticação
- `python-dotenv` - Variáveis de ambiente
- `oracledb` - Conexão com banco Oracle (para validação CNPJ)

### Configuração

1. **Criar arquivo `.env`** em `src/main/api/`:
```
ENERGISA_USER=seu_email@example.com
ENERGISA_PASSWORD=sua_senha
OUTLOOK_USER=email_outlook@outlook.com
OUTLOOK_PASSWORD=senha_outlook
```

2. **Configurar caminhos** em `get_text_coord_xml.py`:
```python
PASTA_PDFS = r"C:\bf_ocr\src\resource\pdf"
PASTA_XML = r"C:\bf_ocr\src\resource\xml"
```

### Execução

**Passo 1: Download de Faturas**
```bash
python src/main/api/Download_faturas.py
```

**Passo 2: Processamento para XML**
```bash
python src/main/coord_text/Faturas_retornando_XML/get_text_coord_xml.py
```

**Passo 3: Envio para Pasta Compartilhada (PRINCIPAL)**
```bash
python src/main/coord_text/Faturas_retornando_XML/post_folder_temp_linux.py
```

---

## 📊 Fluxo de Dados Detalhado

```
┌─────────────────────────────────────────┐
│  Download_faturas.py (Etapa 1)          │
│  - Autenticação Energisa                │
│  - Login automático com MFA             │
│  - Busca de unidades consumidoras       │
│  - Download de PDFs por período         │
└──────────────┬──────────────────────────┘
               │
               ↓ PDFs salvos
       ┌───────────────────┐
       │  /faturas/        │
       │  *.pdf files      │
       └─────────┬─────────┘
               │
               ↓
┌──────────────────────────────────────────┐
│  get_text_coord_xml.py (Etapa 2)         │
│  - Lê PDF com pdfplumber                 │
│  - Extrai texto por coordenadas         │
│  - Processa tabelas de itens            │
│  - Normaliza valores                     │
│  - Consulta CNPJ no banco              │
│  - Remove itens irrelevantes             │
│  - Valida estrutura de dados             │
│  - Converte para XML                     │
└──────────────┬──────────────────────────┘
               │
               ↓ XMLs gerados
       ┌───────────────────┐
       │   /xml/           │
       │  *.xml files      │
       └─────────┬─────────┘
               │
               ↓
┌──────────────────────────────────────────┐
│  post_folder_temp_linux.py (PRINCIPAL)   │
│  - Conexão SMB com servidor              │
│  - Upload recursivo de pastas            │
│  - PDFs e XMLs para compartilhado        │
│  - Logs de sucesso/erro                  │
└──────────────┬──────────────────────────┘
               │
               ↓ Arquivos enviados
       ┌─────────────────────────────────┐
       │  \\192.168.200.20\temporario$\   │
       │  fatura_energisa_bot\           │
       │  (PDFs e XMLs)                  │
       └─────────────────────────────────┘
```

---

## 🔍 Exemplo de Processamento

### Entrada (PDF)
```
ENERGISA - NOTA FISCAL Nº 020.537.640
CLIENTE: EXEMPLO LTDA
CNPJ: 12.345.678/0001-00
ROTEIRO: 12345
MATRICULA: 3359145-4
REFERÊNCIA: 01/2025
TOTAL A PAGAR: R$ 1.234,56

DISCRIMINAÇÃO DO CONSUMO
ENERGIA ATIVA        100 KWH    1.234,56
ICMS                           180,45
```

### Processamento
1. Extrai cada região por coordenadas
2. Limpa formatação (remove "R$", trata separadores)
3. Normaliza valores: "1.234,56" → 1234.56
4. Processa itens: "100 KWH" → quantidade: 100
5. Valida CNPJ no banco de dados
6. Remove itens de compensação/crédito
7. Estrutura dados em dicionário
8. Converte para XML

### Saída (XML)
```xml
<?xml version="1.0" encoding="UTF-8"?>
<fatura>
  <cabecalho>
    <numero_nf>020537640</numero_nf>
    <cnpj_consumidor>12.345.678/0001-00</cnpj_consumidor>
    <nome_cliente>EXEMPLO LTDA</nome_cliente>
    <roteiro>12345</roteiro>
    <matricula>3359145-4</matricula>
    <referencia>01/2025</referencia>
    <total_pagar>1234.56</total_pagar>
  </cabecalho>
  <itens>
    <item>
      <descricao>ENERGIA ATIVA</descricao>
      <quantidade>100</quantidade>
      <unidade>KWH</unidade>
      <valor>1234.56</valor>
    </item>
  </itens>
  <tributos>
    <icms>180.45</icms>
  </tributos>
</fatura>
```

---

## 📝 Logs

Os logs são salvos em:
- **Download:** `./logs/{data}_downloads_faturas_energisa.log`
- **Processamento:** Exibe no console e pode ser redirecionado

Formato:
```
2025-02-04 10:30:45 [INFO] Iniciando login automático...
2025-02-04 10:30:46 [INFO] Token de acesso obtido
2025-02-04 10:30:50 [INFO] Código de segurança validado
2025-02-04 10:31:00 [INFO] Faturas encontradas: 5
2025-02-04 10:31:45 [INFO] Downloads concluídos com sucesso
```

---

## 🛠️ Tecnologias Utilizadas

| Tecnologia | Propósito |
|-----------|-----------|
| **pdfplumber** | Extração precisa de texto de PDFs |
| **requests/curl_cffi** | Requisições HTTP com suporte a JavaScript |
| **MSAL** | Autenticação Microsoft (MFA) |
| **dicttoxml** | Conversão JSON/Dict para XML |
| **oracledb** | Validação de CNPJs em banco Oracle |
| **python-dotenv** | Gerenciamento de variáveis de ambiente |
| **logging** | Registro de operações |
| **concurrent.futures** | Processamento paralelo de arquivos |

---

## 📌 Notas Importantes

1. **Autenticação MFA**: O script automático aguarda código por email/SMS
2. **Coordenadas Fixas**: As coordenadas são específicas para o formato padrão Energisa
3. **Banco de Dados**: Requer conexão Oracle para validação de CNPJs
4. **Tratamento de Valores**: Suporta formatação brasileira (1.234,56) e contábil ((1.234,56))
5. **Processamento Paralelo**: Usa ThreadPoolExecutor para processar múltiplos PDFs

---

## 🐛 Possíveis Melhorias

- [ ] Suporte a múltiplos formatos de PDF (além do padrão Energisa)
- [ ] Detecção automática de coordenadas via ML
- [ ] API REST para integração com sistemas externos
- [ ] Dashboard de monitoramento de downloads
- [ ] Armazenamento em banco de dados estruturado (além de XML)

---

## 📞 Contato / Suporte

Para dúvidas sobre funcionalidades específicas, consulte os comentários no código-fonte dos arquivos principais.

---

**Última atualização:** 04 de fevereiro de 2026
