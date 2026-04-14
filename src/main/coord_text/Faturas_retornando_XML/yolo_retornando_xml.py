from ultralytics import YOLO
from pathlib import Path
import pandas as pd
import fitz  # PyMuPDF
import io
import subprocess
from PIL import Image
import pdfplumber
from datetime import datetime
import re
from typing import Dict, Any, List, Tuple
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from dicttoxml import dicttoxml
from xml.dom.minidom import parseString, Node, Document
from time import sleep
from regioes_pdf import regioes_refaturadas, regioes_fino
import os
import uuid
from smbclient import register_session, open_file
import shutil
from database.connect_oracle import retorno_cnpj_pdf
from dotenv import load_dotenv
load_dotenv()
# --- EXCLUIR ARQUIVOS ANTIGOS ---
resultado = subprocess.run(['ls', '-l'], capture_output=True, text=True)
print(resultado.stdout)

# --- CONFIGURAÇÕES GLOBAIS ---
MODEL_PATH = r'C:/ocr_conta_energia/src/runs/detect/yolov8_notas17/weights/best.pt'
PDF_FOLDER = Path(r'C:/ocr_conta_energia/src/main/api/faturas/')
OUT_DIR = Path(r'C:/ocr_conta_energia/src/runs/runs')
OUT_DIR.mkdir(parents=True, exist_ok=True)
CSV_PATH = OUT_DIR / 'detections_pdf_ram.csv'
DPI = 200  # Resolução para a conversão de PDF para PNG

# Configurações do segundo código
PASTA_PDFS = r'C:/ocr_conta_energia/src/main/api/faturas/'
PASTA_XML = r"C:/ocr_conta_energia/src/main/coord_text/Faturas_retornando_XML/xml"

ITENS_A_EXCLUIR_DO_CONSUMO = [
    "COMPENSACAO POR INDICADOR",
    "COMP.INDICADOR-DIC",
    "ATUALIZAÇÃO MONETARIA",
    "DIF.CREDITO",
    "CONTRIB DE ILUM PUB",
    "ADIC. B. VERMELHA",
    "ADICIONAL CONTA COVID ESCASSEZ HÍDRICA",
    "CUSTO DE DISPONIBILIDADE",
    "DÉBITO TUSD",
    "DEBITO TUSD",
    "CREDITO TUSD",
    "SUBSTITUIÇÃO TRIBUTÁRIA",
    "DEVOLUÇÃO SUBSÍDIO",
]

# --- INICIALIZAÇÃO DO MODELO YOLO ---
model = YOLO(MODEL_PATH)

# --- CARREGAR NOMES DAS CLASSES ---
class_names = None
if hasattr(model, 'names') and model.names:
    class_names = model.names
else:
    names_file = Path(r'C:\yolov2\data\obj.names')
    if names_file.exists():
        class_names = [line.strip() for line in names_file.read_text(encoding='utf-8').splitlines() if line.strip()]


# --- FUNÇÕES DO PRIMEIRO CÓDIGO (DETECÇÃO) ---
def process_pdfs_to_ram(pdf_folder: Path, dpi: int) -> dict:
    """Extrai a 1ª página de cada PDF, converte para Pixmap e usa PIL para PNG em RAM."""
    ram_images = {}
    if not pdf_folder.is_dir():
        print(f"Erro: Pasta PDF não encontrada: {pdf_folder}")
        return ram_images

    pdf_files = list(pdf_folder.glob('*.pdf'))
    if not pdf_files:
        print(f"Nenhum arquivo PDF encontrado em: {pdf_folder}")
        return ram_images

    print(f"Iniciando conversão de {len(pdf_files)} PDFs para PNG na RAM (usando PIL)...")

    for pdf_path in pdf_files:
        try:
            with fitz.open(pdf_path) as doc:
                page = doc.load_page(0)
                zoom_matrix = fitz.Matrix(dpi / 72, dpi / 72)
                pix = page.get_pixmap(matrix=zoom_matrix)

                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                png_buffer = io.BytesIO()
                img.save(png_buffer, format='PNG')
                ram_images[pdf_path.name] = png_buffer.getvalue()
                print(f" Processado para RAM: {pdf_path.name}")

        except Exception as e:
            print(f" Falha ao processar PDF {pdf_path.name}: {e}")

    return ram_images


def detectar_tipo_modelo(pdf_folder: Path) -> Dict[str, str]:
    """
    Analisa todos os PDFs e retorna um dicionário com o tipo de modelo para cada arquivo.
    Retorna: {'nome_arquivo.pdf': 'fino' ou 'refaturado'}
    """
    ram_images = process_pdfs_to_ram(pdf_folder, DPI)
    resultados = {}

    print("\nIniciando detecção do tipo de modelo...")

    for file_name, png_bytes in ram_images.items():
        try:
            image_stream = io.BytesIO(png_bytes)
            pil_image = Image.open(image_stream).convert('RGB')

            results = model.predict(source=pil_image, conf=0.1, imgsz=640, save=False, verbose=False)
            r = results[0]
            boxes = getattr(r, 'boxes', None)

            if not boxes or len(boxes) == 0:
                print(f'❌ Nenhuma detecção em: {file_name}')
                resultados[file_name] = 'desconhecido'
                continue

            # Extrair arrays
            try:
                cls_ids = boxes.cls.cpu().numpy().astype(int)
            except Exception:
                cls_ids = boxes.cls.numpy().astype(int)

            # Determinar o tipo baseado nas classes detectadas
            tipos_detectados = []
            for cid in cls_ids:
                if class_names is not None:
                    if isinstance(class_names, dict):
                        cname = class_names.get(int(cid), str(cid))
                    else:
                        cname = class_names[int(cid)] if int(cid) < len(class_names) else str(cid)
                else:
                    cname = str(cid)
                tipos_detectados.append(cname.lower())

            # Lógica para determinar se é "fino" ou "refaturado"
            if any('refaturado' in tipo or 'refat' in tipo for tipo in tipos_detectados):
                resultados[file_name] = 'refaturado'
            elif any('fino' in tipo for tipo in tipos_detectados):
                resultados[file_name] = 'fino'
            else:
                resultados[file_name] = 'fino'  # padrão

            print(f"✅ {file_name}: {resultados[file_name]}")

        except Exception as e:
            print(f"❌ Erro na detecção para {file_name}: {e}")
            resultados[file_name] = 'desconhecido'

    return resultados


# --- FUNÇOES DO SEGUNDO CÓDIGO (PROCESSAMENTO PDF) ---
def normalizar_valor(valor_str: str) -> float:
    if not valor_str: return 0.0
    valor_limpo = valor_str.strip()
    is_negativo = False

    if valor_limpo.startswith('(') and valor_limpo.endswith(')'):
        valor_limpo = valor_limpo[1:-1]
        is_negativo = True

    if '-' in valor_limpo:
        is_negativo = True
        valor_limpo = valor_limpo.replace('-', '')

    valor_limpo = valor_limpo.replace('.', '').replace(',', '.')

    try:
        valor_float = float(valor_limpo)
        return -abs(valor_float) if is_negativo else valor_float
    except ValueError:
        return 0.0

def remove_empty_values(d: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(d, dict): return d
    new_d = {}
    for k, v in d.items():
        if isinstance(v, dict):
            v = remove_empty_values(v)
            if v: new_d[k] = v
        elif isinstance(v, list):
            v_limpa = [remove_empty_values(item) for item in v if item]
            if v_limpa: new_d[k] = v_limpa
        elif v != "" and v is not None:
            if isinstance(v, str) and not v.strip(): continue
            new_d[k] = v
    return new_d

def calcular_retangulo(coordenadas: List[Tuple[float, float]]):
    x_coords = [coord[0] for coord in coordenadas]
    y_coords = [coord[1] for coord in coordenadas]
    return (min(x_coords), min(y_coords), max(x_coords), max(y_coords))

def extrair_texto_nas_coordenadas(pdf_path: str, retangulo: Tuple[float, float, float, float]) -> str:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pagina = pdf.pages[0]
            palavras = pagina.within_bbox(retangulo).extract_words(
                x_tolerance=3, y_tolerance=3, keep_blank_chars=False, use_text_flow=True
            )
            if not palavras: return "Nenhum texto encontrado"
            linhas = {}
            for palavra in palavras:
                y = round(palavra['top'])
                if y not in linhas: linhas[y] = []
                linhas[y].append((palavra['x0'], palavra['text']))
            texto_ordenado = []
            for y in sorted(linhas.keys()):
                palavras_na_linha = sorted(linhas[y], key=lambda x: x[0])
                linha_texto = ' '.join([palavra[1] for palavra in palavras_na_linha])
                texto_ordenado.append(linha_texto)
            return '\n'.join(texto_ordenado)
    except Exception as e:
        return f"Erro: {str(e)}"

def extrair_texto_por_linhas(pdf_path: str, coordenadas: List[Tuple[float, float]], pagina: int = 0) -> List[
    Dict[str, Any]]:
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pagina_pdf = pdf.pages[pagina]
            area = (coordenadas[0][0], coordenadas[0][1], coordenadas[1][0], coordenadas[1][1])
            return pagina_pdf.within_bbox(area).extract_text_lines()
    except Exception as e:
        return []

def extrair_descricao_valores(texto_linha: str) -> Tuple[str, str]:
    unidades = ["KWH", "KW", "UN"]
    for un in unidades:
        if un in texto_linha:
            partes = texto_linha.split(un, 1)
            return partes[0].strip(), partes[1].strip() if len(partes) > 1 else ""
    m_data = re.search(r"\b\d{2}/\d{4}\b", texto_linha)
    if m_data:
        idx = m_data.end()
        resto = texto_linha[idx:]
        m_num = re.search(r"\d+", resto)
        if m_num:
            return texto_linha[: idx + m_num.start()].strip(), resto[m_num.start():].strip()
    m_num = re.search(r"\d+", texto_linha)
    if m_num:
        return texto_linha[:m_num.start()].strip(), texto_linha[m_num.start():].strip()
    return texto_linha.strip(), ""

##
## --FUNCOES PARA PEGAR OS TEXTOS POR CADA REGIAO DO PDF
##

def processar_tabela_itens(linhas: List[Dict[str, Any]], pdf_path: str) -> List[Dict[str, Any]]:
    itens = []
    if not linhas: return itens
    for linha in linhas:
        texto_linha = linha['text'].strip()
        if not re.search(r"\d", texto_linha) or texto_linha.upper().startswith("TOTAL:"):
            continue

        descricao, valores_str = extrair_descricao_valores(texto_linha)
        is_negativo = '-' in valores_str or '(' in valores_str or '-' in descricao
        valores = re.findall(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+", valores_str)

        item_data = {'descricao': descricao}

        if valores:
            valor_principal = valores[0]
            if is_negativo and not (valor_principal.startswith('-') or valor_principal.startswith('(')):
                valores[0] = f'-{valor_principal}'

        if len(valores) >= 8:
            item_data.update({
                'quantidade': valores[0], 'preco_unit_com_tributos': valores[1], 'valor': valores[2],
                'pis_confins': valores[3], 'base_calc_icms': valores[4], 'porcent_icms': valores[5],
                'icms': valores[6], 'tarifa_unit': valores[7]
            })
        elif len(valores) == 5:
            item_data.update({
                'valor': valores[0], 'pis_confins': valores[1], 'base_calc_icms': valores[2],
                'porcent_icms': valores[3], 'icms': valores[4]
            })
        elif valores:
            item_data.update({'valor': valores[0]})

        itens.append(item_data)
    return itens

def processar_cnpj(texto: str, nome_titular="") -> dict:
    resultado = {}
    linhas = texto.split('\n')
    num_cnpj = re.findall(r'\d', linhas[0])
    ult_num = (num_cnpj[-3:])
    prim_num = (num_cnpj[0])
    ult_num = ''.join(ult_num)

    num_insc = re.findall(r'\d+', linhas[1])
    num_insc = ''.join(num_insc)
    nome_titular = re.sub(r"\bS\.?\s?A\b", "", nome_titular, flags=re.I)

    cnpj_dados_brutos = retorno_cnpj_pdf(prim_num, ult_num, nome_titular, num_insc) 
    #cnpj_dados_brutos = []  # Placeholder

    cnpj_completo_str = ""
    if isinstance(cnpj_dados_brutos, list) and len(cnpj_dados_brutos) > 0:
        primeiro_elemento = cnpj_dados_brutos[0]
        if isinstance(primeiro_elemento, tuple) and len(primeiro_elemento) > 0:
            cnpj_completo_str = str(primeiro_elemento[0])

    resultado = {"cnpj_consumidor": cnpj_completo_str}
    return resultado

def processar_roteiro_tensao(texto: str) -> Dict[str, Any]:
    linhas = [linha.strip() for linha in texto.split('\n') if linha.strip()]
    resultado = {}
    if len(linhas) >= 1:
        roteiro_match = re.search(r'ROTEIRO:\s*([\d\s\-]+)', linhas[0], re.IGNORECASE)
        resultado["roteiro"] = roteiro_match.group(1).strip() if roteiro_match else ""
    if len(linhas) >= 2:
        matricula_match = re.search(r'MATRÍCULA:\s*([\d\-]+)', linhas[1], re.IGNORECASE)
        resultado["matricula"] = matricula_match.group(1).strip() if matricula_match else ""
    if len(linhas) >= 4:
        texto_classificacao = ' '.join(linhas[3:])
        info_classificacao = {}
        ligacao_match = re.search(r'(TRIFASICO|MONOFASICO|BIFASICO)', texto_classificacao, re.IGNORECASE)
        info_classificacao["ligacao"] = ligacao_match.group(1).upper() if ligacao_match else ""
        resultado["classificacao"] = info_classificacao
    for linha in linhas:
        disp_match = re.search(r'DISP\s*[:]?\s*(\d+)', linha, re.IGNORECASE)
        if disp_match:
            resultado["disp"] = disp_match.group(1)
            break
    else:
        resultado["disp"] = ""
    return resultado

def processar_nota_fiscal_protocolo(texto: str) -> Dict[str, Any]:
    linhas = texto.split('\n')
    resultado = {}

    padraoChaveAcesso = r'(\d{4}\s*){11,}' 

    # BUSQUE NO TEXTO BRUTO (string), NÃO NA LISTA
    match = re.search(padraoChaveAcesso, texto)

    if match:
        # Remove espaços e quebras de linha para juntar tudo
        chaveAcesso = re.sub(r'\s+', '', match.group(0))
        print(f"Chave encontrada: {chaveAcesso}")
        resultado["chave_acesso"] = chaveAcesso

    if len(linhas) >= 1:
        nf_match = re.search(r'\b\d{3}\.\d{3}\.\d{3}\b', linhas[0])
        resultado["numero_nota_fiscal"] = nf_match.group().replace('.', '').lstrip('0') if nf_match else ""
        nf_serie = re.search(r's[eé]rie\s*:\s*(\d+)', linhas[0], re.IGNORECASE)
        if nf_serie:
            num = nf_serie.group(1)
            resultado["serie_nota_fiscal"] = num[-1] if len(num) > 1 and int(num) != 0 else num
        else:
            resultado["serie_nota_fiscal"] = ""
    if len(linhas) >= 2:
        data_match = re.search(r'\b\d{2}/\d{2}/\d{4}\b', linhas[1])
        resultado["data_emissao"] = data_match.group() if data_match else ""

    return resultado

def processar_cnpj_mod_fino(texto):
    linhas = texto.split('\n')
    resultado = ""

    if linhas:
        m = re.search(r'CNPJ/CPF:\s*([\d./-]+)', linhas[0])
        if m:
            doc_com_pontuacao = m.group(1)
            resultado = re.sub(r'\D', '', doc_com_pontuacao)

    return resultado

def processar_nome_endereco(texto: str) -> Dict[str, Any]:
    linhas = texto.split('\n')
    resultado = {}
    if len(linhas) >= 1: resultado["nome_titular"] = linhas[0].strip()
    if len(linhas) >= 2:
        endereco = []
        for i in range(1, min(4, len(linhas))):
            if i < len(linhas): endereco.append(linhas[i].strip())
        resultado["endereco"] = ' '.join(endereco)
    return resultado

def processar_codigo_cliente(texto: str) -> Dict[str, Any]:
    linhas = texto.split('\n')
    resultado = {}
    if len(linhas) >= 1:
        codigo_completo = re.search(r'[\d/]+-?\d*', linhas[0])
        resultado["codigo_cliente"] = codigo_completo.group() if codigo_completo else linhas[0].strip()
    return resultado

def processar_ref_total_pagar(texto: str) -> Dict[str, Any]:
    linhas = texto.split('\n')
    resultado = {}
    if linhas:
        linha_principal = linhas[0]
        ref_match = re.search(r'([A-Za-zçÇ]+)\s*/\s*(\d{4})', linha_principal, re.IGNORECASE)
        resultado["mes_ano_referencia"] = f"{ref_match.group(1)}/{ref_match.group(2)}" if ref_match else ""
        vencimento_match = re.search(r'\b\d{2}/\d{2}/\d{4}\b', linha_principal)
        resultado["data_vencimento"] = vencimento_match.group() if vencimento_match else ""
        total_match = re.search(r'R\$\s*([\d.,]+)', linha_principal)
        resultado["total_pagar"] = total_match.group(1) if total_match else ""
    return resultado

def processar_tributos(texto: str) -> Dict[str, Any]:
    resultado = {}

    def extrair_valores_tributo(tag, texto):
        padrao = fr"{tag}\s+([\d.,]+)\s+([\d.,]+)\s+([\d.,]+)"
        m = re.search(padrao, texto, re.IGNORECASE)
        return {
            "base_calculo": m.group(1) if m else "",
            "aliquota": m.group(2) if m else "",
            "valor": m.group(3) if m else ""
        }

    texto_unico = ' '.join([linha.strip() for linha in texto.split('\n') if linha.strip()])

    resultado["pis"] = extrair_valores_tributo("PIS/PASEP", texto_unico)
    if all(v == "" for v in resultado["pis"].values()): del resultado["pis"]

    resultado["cofins"] = extrair_valores_tributo("COFINS", texto_unico)
    if all(v == "" for v in resultado["cofins"].values()): del resultado["cofins"]

    resultado["icms"] = extrair_valores_tributo("ICMS", texto_unico)
    if all(v == "" for v in resultado["icms"].values()): del resultado["icms"]

    return resultado

def processar_regiao_parallel(caminho_pdf, modelo_tipo):
    """
    Processa todas as regiões do PDF usando as coordenadas corretas baseadas no tipo de modelo.
    """
    resultado_plano = {}
    tributos_data = {}
    itens_tabela_brutos = []

    # SELECIONA AS REGIÕES CORRETAS BASEADO NO TIPO DE MODELO
    if modelo_tipo == 'refaturado':
        regioes = regioes_refaturadas
    else:  # fino ou desconhecido
        regioes = regioes_fino

    for nome_regiao, info_regiao in regioes.items():
        if nome_regiao == 'tabela_itens':
            linhas_brutas = extrair_texto_por_linhas(caminho_pdf, info_regiao['coordenadas'])
            itens_tabela_brutos = processar_tabela_itens(linhas_brutas, caminho_pdf)
            continue

        texto = extrair_texto_nas_coordenadas(caminho_pdf, calcular_retangulo(info_regiao['coordenadas']))

        try:
            if nome_regiao == 'tributos':
                tributos_data = processar_tributos(texto)
            elif nome_regiao == 'ref_total_pagar':
                resultado_plano['pagamento'] = processar_ref_total_pagar(texto)
            elif nome_regiao == 'nota_fiscal_protocolo':
                resultado_plano['nota_fiscal'] = processar_nota_fiscal_protocolo(texto)
            elif nome_regiao == 'cnpj':
                nome_titular = resultado_plano.get('cliente', {}).get('nome_titular', '')
                resultado_plano['cnpj'] = processar_cnpj(texto, nome_titular)
            elif nome_regiao == 'cnpj_fino' and modelo_tipo == 'fino':
                resultado_plano['cnpj'] = {"cnpj_consumidor": processar_cnpj_mod_fino(texto)}
            elif nome_regiao == 'codigo_cliente':
                resultado_plano['codigo_cliente'] = processar_codigo_cliente(texto)
            elif nome_regiao == 'nome_endereco':
                resultado_plano['cliente'] = processar_nome_endereco(texto)
            elif nome_regiao == 'roteiro_tensao':
                resultado_plano['roteiro_tensao'] = processar_roteiro_tensao(texto)
        except Exception as e:
            print(f"A região {nome_regiao} não está presente nas coordenadas: {e}")

    return resultado_plano, tributos_data, itens_tabela_brutos


def extrair_informacoes_estruturadas(resultado_plano: Dict[str, Any], tributos_data: Dict[str, Any],
                                     itens_tabela_brutos: List[Dict[str, Any]]) -> Dict[str, Any]:
    def criar_item_tributo(nome_tributo: str, dados_tributo: Dict[str, str]) -> Dict[str, Any]:
        if not dados_tributo: return None
        valor = dados_tributo.get('valor', '').strip()
        if not valor or normalizar_valor(valor) == 0.0: return None
        return {
            'descricao': f"VALOR TOTAL {nome_tributo.upper()}",
            'valor': valor,
        }

    def formatar_valor_br(valor_float: float) -> str:
        return f"{valor_float:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

    todos_os_itens = []
    todos_os_itens.extend(itens_tabela_brutos)

    for tributo in ['pis', 'cofins', 'icms']:
        if tributo in tributos_data:
            item = criar_item_tributo(tributo.upper(), tributos_data[tributo])
            if item:
                todos_os_itens.append(item)

    valor_total_str = resultado_plano.get('pagamento', {}).get("total_pagar", "0,00")
    valor_total = normalizar_valor(valor_total_str)
    if valor_total_str == '0,00':
        valor_total_str = '0,01'

    total_taxas_a_excluir = 0.0
    for item in todos_os_itens:
        descricao = item.get('descricao', '').upper()
        valor = normalizar_valor(item.get('valor', '0,00'))

        if any(termo in descricao for termo in ITENS_A_EXCLUIR_DO_CONSUMO):
            if valor < 0:
                continue
            total_taxas_a_excluir += valor

    consumo_real = max(valor_total - total_taxas_a_excluir, 0.0)
    total_taxas_consolidadas = valor_total - consumo_real

    itens_fatura_dict = {}
    itens_fatura_dict['ValorConsumo'] = formatar_valor_br(consumo_real)

    if total_taxas_consolidadas > 0.0:
        itens_fatura_dict['ValorTaxas'] = formatar_valor_br(total_taxas_consolidadas)

    icms_data = tributos_data.get('icms', {})
    base_calc_icms_float = normalizar_valor(icms_data.get('base_calculo', '0,00'))
    aliquota_icms_str = icms_data.get('aliquota', '0,00')
    valor_icms_float = normalizar_valor(icms_data.get('valor', '0,00'))

    itens_fatura_dict['BaseCalculoICMS'] = formatar_valor_br(base_calc_icms_float)
    itens_fatura_dict['AliquotaICMS'] = aliquota_icms_str.replace('.', ',')
    itens_fatura_dict['ValorICMS'] = formatar_valor_br(valor_icms_float)

    nota_fiscal_data = resultado_plano.get('nota_fiscal', {})
    pagamento_data = resultado_plano.get('pagamento', {})
    consumo_energia_str = formatar_valor_br(consumo_real)

    cnpj_dados_brutos = resultado_plano.get('cnpj', {})
    cnpj_completo_valor = ""
    if isinstance(cnpj_dados_brutos, dict):
        cnpj_completo_valor = cnpj_dados_brutos.get("cnpj_consumidor", "")
    elif isinstance(cnpj_dados_brutos, list) and len(cnpj_dados_brutos) > 0:
        if isinstance(cnpj_dados_brutos[0], list) and len(cnpj_dados_brutos[0]) > 0:
            cnpj_completo_valor = cnpj_dados_brutos[0][0]

    cabecalho = {
        "TipoDocumento": "nfcee",
        "EspecieDocumento": "nfcee",
        "DataEmissao": nota_fiscal_data.get("data_emissao", ""),
        "NumeroDocumento": nota_fiscal_data.get("numero_nota_fiscal", ""),
        "Serie": nota_fiscal_data.get("serie_nota_fiscal", ""),
        "ChaveAcesso": nota_fiscal_data.get("chave_acesso", ""),
        "CnpjConsumidor": cnpj_completo_valor,
        "ValorTotal": valor_total_str,
        "CodigoCliente": resultado_plano.get('codigo_cliente', {}).get('codigo_cliente', ''),
        "ReferenciaMesAno": pagamento_data.get("mes_ano_referencia", ""),
        "DataVencimento": pagamento_data.get("data_vencimento", ""),
    }

    cabecalho_limpo = remove_empty_values(cabecalho)

    resultado_estruturado = {
        "cabecalho": cabecalho_limpo,
        "itens": itens_fatura_dict
    }

    return resultado_estruturado

def filtrar_faturas_duplicadas(todas_faturas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    faturas_por_cliente = {}

    for fatura in todas_faturas:
        cabecalho = fatura.get('cabecalho', {})
        codigo_cliente = cabecalho.get('CodigoCliente')
        data_emissao_str = cabecalho.get('DataEmissao')

        if not codigo_cliente or not data_emissao_str:
            if codigo_cliente not in faturas_por_cliente:
                faturas_por_cliente[f'{codigo_cliente}_ou_sem_data'] = [fatura]
            continue

        try:
            data_emissao = datetime.strptime(data_emissao_str, '%d/%m/%Y')
        except ValueError:
            if codigo_cliente not in faturas_por_cliente:
                faturas_por_cliente[f'{codigo_cliente}_ou_sem_data'] = [fatura]
            continue

        cliente_key = codigo_cliente

        if cliente_key not in faturas_por_cliente:
            faturas_por_cliente[cliente_key] = (data_emissao, fatura)
        else:
            data_existente, fatura_existente = faturas_por_cliente[cliente_key]
            if data_emissao > data_existente:
                faturas_por_cliente[cliente_key] = (data_emissao, fatura)

    return [fatura for _, fatura in faturas_por_cliente.values()]

def salvar_xmls_por_uc(faturas_dados: List[Dict[str, Any]], pasta_saida: str):
    if not faturas_dados:
        print("Nenhuma fatura para salvar.")
        return

    Path(pasta_saida).mkdir(parents=True, exist_ok=True)
    lista_xml_strings = converter_lote_para_xml_separado(faturas_dados)

    for i, xml_string in enumerate(lista_xml_strings):
        dados_fatura = faturas_dados[i]
        uc = dados_fatura.get('cabecalho', {}).get('CodigoCliente')
        nome_original_pdf = dados_fatura.get('@nome', f"arquivo_{i}.pdf")
        unidade_consumidora = uc.replace('\\', '').replace('/', '').replace('-', '') if uc else f"sem_uc_{i}"

        if not uc:
            print(f"Aviso: Código de cliente não encontrado para o arquivo {nome_original_pdf}.")

        nome_base = Path(nome_original_pdf).stem
        nome_arquivo_saida = f"{unidade_consumidora}.xml"
        caminho_saida = Path(pasta_saida) / nome_arquivo_saida

        try:
            with open(caminho_saida, 'w', encoding='utf-8') as f:
                f.write(xml_string)
            print(f"XML salvo com sucesso: {caminho_saida.name}")
        except Exception as e:
            print(f"Erro ao salvar o arquivo {nome_arquivo_saida}: {e}")

def converter_lote_para_xml_separado(lote_dados: List[Dict[str, Any]]) -> List[str]:
    lista_xml = []

    for dados_fatura in lote_dados:
        try:
            xml_bytes = dicttoxml(
                dados_fatura,
                custom_root='NotaFiscalEnergia',
                attr_type=False,
                item_func=lambda x: 'fatura_detalhe'
            )

            dom = parseString(xml_bytes)
            root = dom.documentElement

            keys_to_remove = []
            for child in list(root.childNodes):
                if child.nodeType == Node.ELEMENT_NODE and child.tagName == 'key':
                    key_name = child.getAttribute('name')
                    key_value = child.firstChild.nodeValue if child.firstChild else ""

                    if key_name == '@id':
                        keys_to_remove.append(child)
                    elif key_name == '@nome':
                        root.setAttribute('nome', key_value)
                        keys_to_remove.append(child)

            for key_node in keys_to_remove:
                root.removeChild(key_node)

            tags_para_forcar_abertura = [
                'CnpjConsumidor',
                'ValorConsumo',
                'ValorTaxas',
                'BaseCalculoICMS',
                'AliquotaICMS',
                'ValorICMS'
            ]

            for tag_name in tags_para_forcar_abertura:
                for tag_node in dom.getElementsByTagName(tag_name):
                    if not tag_node.hasChildNodes():
                        tag_node.appendChild(dom.createTextNode(''))

            xml_formatado = dom.toprettyxml(indent="  ")
            xml_final = "\n".join(xml_formatado.split('\n')[1:]).strip()
            lista_xml.append(xml_final)

        except Exception as e:
            print(f"Erro ao manipular/formatar XML para um dos arquivos: {e}")
            lista_xml.append(f"ERRO NO PROCESSAMENTO: {e}")

    return lista_xml

# --- FUNÇÃO PARA ENVIAR AS FATURAS VIA SMB PARA PASTA RPAENERGIA ---
def enviar_faturas():
    server = "faturaenergia"
    username = "bf.bot@bomfuturo.com.br"
    password = "k4$ov7@Jçt"
    share = "rpaenergia"
    # Certifique-se de que este caminho está correto e acessível
    local_folder = r"C:/ocr_conta_energia/main/api/faturas/"

    try:
        # 1. Autenticação (Já sabemos que funciona!)
        register_session(server, username=username, password=password)
        print("Sessão registrada!")

        # 2. Listar arquivos locais
        arquivos = os.listdir(local_folder)
        if not arquivos:
            print("Nao existem arquivos na pasta local.")
            return

        for arquivo in arquivos:
            caminho_local = os.path.join(local_folder, arquivo)

            # Garantir que é um arquivo
            if os.path.isfile(caminho_local):
                # O caminho remoto deve começar com \\servidor\compartilhamento
                caminho_remoto = f"\\\\{server}\\{share}\\{arquivo}"

                print(f"Enviando: {arquivo}...", end=" ")

                try:
                    # Lendo o arquivo local e escrevendo no remoto
                    with open(caminho_local, 'rb') as f_local:
                        with open_file(caminho_remoto, mode='wb') as f_remoto:
                            shutil.copyfileobj(f_local, f_remoto)
                    print("✓")
                except Exception as e:
                    print(f" Erro: {e}")

        print("\nProcesso concluído com sucesso!")

    except Exception as e:
        print(f"Erro na conexão: {e}")

# --- FUNÇÃO PRINCIPAL INTEGRADA ---
def main():
    # 1. Primeiro detecta o tipo de modelo para todos os PDFs
    print("=== FASE 1: DETECÇÃO DO TIPO DE MODELO ===")
    tipos_modelo = detectar_tipo_modelo(Path(PASTA_PDFS))

    # 2. Depois processa cada PDF com as coordenadas corretas
    print("\n=== FASE 2: PROCESSAMENTO DOS PDFs ===")
    caminho_pasta = Path(PASTA_PDFS)
    arquivos_pdf = list(caminho_pasta.glob("*.pdf"))

    if not arquivos_pdf:
        print(f"Nenhum arquivo PDF encontrado na pasta: {PASTA_PDFS}")
        return

    todas_faturas = []

    for i, caminho_pdf in enumerate(arquivos_pdf, 1):
        nome_arquivo = caminho_pdf.name
        modelo_tipo = tipos_modelo.get(nome_arquivo, 'fino')  # padrão para 'fino' se não detectado

        print(f"Processando ({i}/{len(arquivos_pdf)}): {nome_arquivo} - Modelo: {modelo_tipo}")

        resultado_plano, tributos_data, itens_tabela_brutos = processar_regiao_parallel(
            str(caminho_pdf), modelo_tipo
        )

        dados_extraidos = extrair_informacoes_estruturadas(
            resultado_plano, tributos_data, itens_tabela_brutos
        )

        dados_extraidos['@id'] = str(i)
        dados_extraidos['@nome'] = nome_arquivo

        todas_faturas.append(dados_extraidos)

    if todas_faturas:
        faturas_filtradas = filtrar_faturas_duplicadas(todas_faturas)
        salvar_xmls_por_uc(faturas_filtradas, PASTA_XML)
        enviar_faturas()
        print("\nProcessamento concluído. XMLs salvos na pasta:", PASTA_XML)

if __name__ == "__main__":
    main()
