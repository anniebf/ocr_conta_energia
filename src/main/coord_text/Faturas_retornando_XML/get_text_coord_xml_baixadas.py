import pdfplumber
from datetime import datetime
import re
from typing import Dict, Any, List, Tuple
from pathlib import Path
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from dicttoxml import dicttoxml
from database.connect_oracle import retorno_cnpj_pdf
from xml.dom.minidom import parseString, Node, Document
from time import sleep
from regioes_pdf import regioes_refaturadas, regioes_fino

regioes = regioes_refaturadas

# CONFIGURAÇÃO
PASTA_PDFS = r"C:\bf_ocr\src\main\api\faturas"
PASTA_XML="C:\\bf_ocr\\\src\\resource\\xml"

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


def normalizar_valor(valor_str: str,) -> float:
    """
    Converte string de valor (ex: '1.234,56', '(1.234,56)', '-1.234,56') em float.
    Lida com formato contábil (parênteses), sinal de menos em qualquer posição
    e formatação de milhar/decimal brasileira.
    """
    if not valor_str: return 0.0

    valor_limpo = valor_str.strip()
    is_negativo = False

    #Verifica e trata formato contábil com parênteses
    if valor_limpo.startswith('(') and valor_limpo.endswith(')'):
        valor_limpo = valor_limpo[1:-1]
        is_negativo = True

    #Verifica se há sinal de menos no início ou fim
    if '-' in valor_limpo:
        is_negativo = True

        valor_limpo = valor_limpo.replace('-', '')

    #Remove separadores de milhar e troca decimal
    valor_limpo = valor_limpo.replace('.', '')
    valor_limpo = valor_limpo.replace(',', '.')

    try:
        valor_float = float(valor_limpo)
        if is_negativo:
            return -abs(valor_float)
        return valor_float

    except ValueError:
        return 0.0


def remove_empty_values(d: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursivamente remove chaves com valores vazios (None, "", {}, [])
    de um dicionário, exceto quando explicitamente mantidas (no cabecalho_limpo).
    """
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


def extrair_texto_por_linhas(pdf_path: str, coordenadas: List[Tuple[float, float]], pagina: int = 0) -> List[Dict[str, Any]]:
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


def processar_tabela_itens(linhas: List[Dict[str, Any]], pdf_path: str) -> List[Dict[str, Any]]:
    itens = []
    if not linhas: return itens
    for linha in linhas:
        texto_linha = linha['text'].strip()
        if not re.search(r"\d", texto_linha) or texto_linha.upper().startswith("TOTAL:"):
            continue

        descricao, valores_str = extrair_descricao_valores(texto_linha)

        # VERIFICAÇÃO DE SINAL NEGATIVO NA STRING BRUTA
        is_negativo = '-' in valores_str or '(' in valores_str or '-' in descricao

        # O seu regex atual precisa ser robusto para capturar valores negativos
        valores = re.findall(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+", valores_str)

        item_data = {'descricao': descricao}

        #APLICAÇÃO DO SINAL NEGATIVO AO PRIMEIRO VALOR ENCONTRADO (QUE DEVE SER O VALOR DO ITEM)
        if valores:
            valor_principal = valores[0]

            if is_negativo and not (valor_principal.startswith('-') or valor_principal.startswith('(')):
                # Garante que o sinal de menos esteja no valor para que normalizar_valor o reconheça
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
    #print(ult_num)

    #print(linhas)
    num_insc = re.findall(r'\d+', linhas[1])
    num_insc = ''.join(num_insc)

    cnpj_dados_brutos = retorno_cnpj_pdf(prim_num, ult_num, nome_titular, num_insc)

    cnpj_completo_str = ""
    if isinstance(cnpj_dados_brutos, list) and len(cnpj_dados_brutos) > 0:
        primeiro_elemento = cnpj_dados_brutos[0]
        if isinstance(primeiro_elemento, tuple) and len(primeiro_elemento) > 0:
            cnpj_completo_str = str(primeiro_elemento[0])

    resultado = {
        "cnpj_consumidor": cnpj_completo_str,
    }
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
    if len(linhas) >= 1:
        nf_match = re.search(r'\b\d{3}\.\d{3}\.\d{3}\b', linhas[0])
        resultado["numero_nota_fiscal"] = nf_match.group().replace('.', '').lstrip('0') if nf_match else ""
        nf_serie = re.search(r'Série:\s*(\d+)', linhas[0])
        if nf_serie:
            num = nf_serie.group(1)
            resultado["serie_nota_fiscal"] = num[-1] if len(num) > 1 and int(num) != 0 else num
        else:
            resultado["serie_nota_fiscal"] = ""
    if len(linhas) >= 2:
        data_match = re.search(r'\b\d{2}/\d{2}/\d{4}\b', linhas[1])
        resultado["data_emissao"] = data_match.group() if data_match else ""
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
    linhas = [linha.strip() for linha in texto.split('\n') if linha.strip()]
    resultado = {}

    def extrair_valores_tributo(texto):
        valores = re.findall(r'[\d.,]+', texto)
        return {
            "base_calculo": valores[0] if len(valores) >= 3 else "",
            "aliquota": valores[1] if len(valores) >= 3 else "",
            "valor": valores[2] if len(valores) >= 3 else ""
        }

    if len(linhas) >= 2:
        resultado["pis"] = extrair_valores_tributo(' '.join(linhas[0:2]))
        if all(v == "" for v in resultado["pis"].values()): del resultado["pis"]

    if len(linhas) >= 3:
        resultado["cofins"] = extrair_valores_tributo(linhas[2])
        if all(v == "" for v in resultado["cofins"].values()): del resultado["cofins"]

    if len(linhas) >= 4:
        resultado["icms"] = extrair_valores_tributo(linhas[3])
        if all(v == "" for v in resultado["icms"].values()): del resultado["icms"]

    return resultado


def processar_regiao_parallel(caminho_pdf):
    """
    Processa todas as regiões do PDF. Retorna 3 valores.
    """
    resultado_plano = {}
    tributos_data = {}
    itens_tabela_brutos = []

    for nome_regiao, info_regiao in regioes.items():

        if nome_regiao == 'tabela_itens':
            linhas_brutas = extrair_texto_por_linhas(caminho_pdf, info_regiao['coordenadas'])
            itens_tabela_brutos = processar_tabela_itens(linhas_brutas, caminho_pdf)
            continue

        texto = extrair_texto_nas_coordenadas(caminho_pdf, calcular_retangulo(info_regiao['coordenadas']))
        #sleep(1)
        #print(texto)
        if nome_regiao == 'tributos':
            tributos_data = processar_tributos(texto)
        elif nome_regiao == 'ref_total_pagar':
            resultado_plano['pagamento'] = processar_ref_total_pagar(texto)
        elif nome_regiao == 'nota_fiscal_protocolo':
            resultado_plano['nota_fiscal'] = processar_nota_fiscal_protocolo(texto)
        elif nome_regiao == 'cnpj':
            nome_titular = resultado_plano.get('cliente', {}).get('nome_titular', '')
            resultado_plano['cnpj'] = processar_cnpj(texto, nome_titular)
        elif nome_regiao == 'codigo_cliente':
            resultado_plano['codigo_cliente'] = processar_codigo_cliente(texto)
        elif nome_regiao == 'nome_endereco':
            resultado_plano['cliente'] = processar_nome_endereco(texto)
        elif nome_regiao == 'roteiro_tensao':
            resultado_plano['roteiro_tensao'] = processar_roteiro_tensao(texto)
        '''elif nome_regiao == 'mais_a_cima':
            resultado_plano['informacoes_superiores'] = processar_area_mais_acima(texto)'''

    # CORRETO: Retorna 3 valores
    return resultado_plano, tributos_data, itens_tabela_brutos


def extrair_informacoes_estruturadas(resultado_plano: Dict[str, Any], tributos_data: Dict[str, Any],itens_tabela_brutos: List[Dict[str, Any]]) -> Dict[str, Any]:
    def criar_item_tributo(nome_tributo: str, dados_tributo: Dict[str, str]) -> Dict[str, Any]:
        """Cria um item de fatura a partir de dados de tributo."""
        if not dados_tributo: return None
        valor = dados_tributo.get('valor', '').strip()
        if not valor or normalizar_valor(valor) == 0.0: return None
        return {
            'descricao': f"VALOR TOTAL {nome_tributo.upper()}",  # Em maiúsculas para bater com ITENS_A_EXCLUIR
            'valor': valor,
        }

    def formatar_valor_br(valor_float: float) -> str:
        """Formata float para string no formato BR (1.234,56)."""
        return f"{valor_float:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')

    # Agrega todos os itens a serem consolidados (tabela + tributos)
    todos_os_itens = []
    todos_os_itens.extend(itens_tabela_brutos)

    for tributo in ['pis', 'cofins', 'icms']:
        if tributo in tributos_data:
            item = criar_item_tributo(tributo.upper(), tributos_data[tributo])
            if item:
                todos_os_itens.append(item)

    # Determinação dos valores consolidados
    valor_total_str = resultado_plano.get('pagamento', {}).get("total_pagar", "0,00")
    valor_total = normalizar_valor(valor_total_str)
    if valor_total_str =='0,00':
        valor_total_str = '0,01'
    total_taxas_a_excluir = 0.0
    for item in todos_os_itens:
        descricao = item.get('descricao', '').upper()
        # Aqui, 'valor' JÁ É UM FLOAT NEGATIVO (ex: -1234.56) se a string de origem tinha o '-'
        valor = normalizar_valor(item.get('valor', '0,00'))

        # Lógica de exclusão de taxa/serviço
        if any(termo in descricao for termo in ITENS_A_EXCLUIR_DO_CONSUMO):

            if valor < 0:
                continue  # Não soma ao total_taxas_a_excluir, pula para o próximo item

            # Se a taxa for POSITIVA, ela é adicionada para ser excluída do consumo.
            total_taxas_a_excluir += valor  #
    #print(f"Valor Total da Nota (zzb_valor): {valor_total}")
    #print(f"Itens Brutos Encontrados (Tabela + Tributos):\n{json.dumps(todos_os_itens, indent=2)}")
    #print(f"Total de Taxas a Excluir (Identificado pela lista ITENS_A_EXCLUIR_DO_CONSUMO): {total_taxas_a_excluir}")
    # Cálculo de Consumo e Taxas Consolidadas

    consumo_real = max(valor_total - total_taxas_a_excluir, 0.0)
    total_taxas_consolidadas = valor_total - consumo_real

    # Criação dos Itens Consolidados (VALOR ÚNICO)
    itens_fatura_dict = {}

    # Consumo é sempre adicionado
    itens_fatura_dict['ValorConsumo'] = formatar_valor_br(consumo_real)

    # Taxas/Serviços são adicionadas apenas se > 0.0
    if total_taxas_consolidadas > 0.0:
        itens_fatura_dict['ValorTaxas'] = formatar_valor_br(total_taxas_consolidadas)

    icms_data = tributos_data.get('icms', {})

    #Base de Cálculo (vinda da área 'tributos', ou 0.0 se não existir)
    base_calc_icms_float = normalizar_valor(icms_data.get('base_calculo', '0,00'))

    # Alíquota (vinda da área 'tributos', ou 0,00 se não existir)
    aliquota_icms_str = icms_data.get('aliquota', '0,00')

    #Valor do ICMS (vinda da área 'tributos', ou 0.0 se não existir)
    valor_icms_float = normalizar_valor(icms_data.get('valor', '0,00'))

    # Inclusão no dicionário, formatando os floats para strings BR
    itens_fatura_dict['BaseCalculoICMS'] = formatar_valor_br(base_calc_icms_float)
    itens_fatura_dict['AliquotaICMS'] = aliquota_icms_str.replace('.',',')
    itens_fatura_dict['ValorICMS'] = formatar_valor_br(valor_icms_float)

    nota_fiscal_data = resultado_plano.get('nota_fiscal', {})
    pagamento_data = resultado_plano.get('pagamento', {})
    consumo_energia_str = formatar_valor_br(consumo_real)

    cnpj_dados_brutos = resultado_plano.get('cnpj', {})
    cnpj_completo_valor = ""
    if isinstance(cnpj_dados_brutos, dict):

        cnpj_completo_valor = cnpj_dados_brutos.get("cnpj_consumidor", "")
        #print(cnpj_completo_valor)
    elif isinstance(cnpj_dados_brutos, list) and len(cnpj_dados_brutos) > 0:
        if isinstance(cnpj_dados_brutos[0], list) and len(cnpj_dados_brutos[0]) > 0:
            cnpj_completo_valor = cnpj_dados_brutos[0][0]


    cabecalho = {
        "TipoDocumento": "nfcee",
        "EspecieDocumento": "nfcee",
        "DataEmissao": nota_fiscal_data.get("data_emissao", ""),
        "NumeroDocumento": nota_fiscal_data.get("numero_nota_fiscal", ""),
        "Serie": nota_fiscal_data.get("serie_nota_fiscal", ""),
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
    """
    Filtra a lista de faturas, mantendo apenas a fatura mais recente
    para cada unidade consumidora duplicado.
    """
    faturas_por_cliente = {}

    for fatura in todas_faturas:
        cabecalho = fatura.get('cabecalho', {})
        codigo_cliente = cabecalho.get('CodigoCliente')
        data_emissao_str = cabecalho.get('DataEmissao')

        if not codigo_cliente or not data_emissao_str:
            # Se faltar o código do cliente ou a data
            print(
                f"Aviso: Fatura {fatura.get('@nome', 'sem nome')} será mantida - faltando código de cliente ou data de emissão.")
            if codigo_cliente not in faturas_por_cliente:
                faturas_por_cliente[f'{codigo_cliente}_ou_sem_data'] = [fatura]
            continue

        try:
            data_emissao = datetime.strptime(data_emissao_str, '%d/%m/%Y')
        except ValueError:
            print(
                f"Aviso: Fatura {fatura.get('@nome', 'sem nome')} com formato de data inválido ({data_emissao_str}). Será mantida.")
            # Trata como única
            if codigo_cliente not in faturas_por_cliente:
                faturas_por_cliente[f'{codigo_cliente}_ou_sem_data'] = [fatura]
            continue

        # Estrutura de armazenamento: (data_emissao_datetime, fatura_dict)
        cliente_key = codigo_cliente

        if cliente_key not in faturas_por_cliente:
            # Primeira fatura para este cliente
            faturas_por_cliente[cliente_key] = (data_emissao, fatura)
        else:
            # Faturas subsequentes: verifica se é mais recente
            data_existente, fatura_existente = faturas_por_cliente[cliente_key]

            if data_emissao > data_existente:
                # Substitui a fatura mais antiga pela nova
                print(
                    f"Substituindo fatura de {cliente_key}: '{fatura_existente.get('@nome')}' ({data_existente.strftime('%d/%m/%Y')}) por '{fatura.get('@nome')}' ({data_emissao_str}).")
                faturas_por_cliente[cliente_key] = (data_emissao, fatura)
            elif data_emissao < data_existente:
                # Descarta a fatura atual
                print(
                    f"Descartando fatura de {cliente_key}: '{fatura.get('@nome')}' ({data_emissao_str}) - mais antiga que a já registrada ('{fatura_existente.get('@nome')}').")
            else:
                # Datas iguais, pode manter a primeira ou a última encontrada (mantendo a última aqui)
                print(
                    f"Aviso: Faturas de {cliente_key} com a mesma data de emissão ({data_emissao_str}). Mantendo a última encontrada.")
                faturas_por_cliente[cliente_key] = (data_emissao, fatura)

    # Retorna a lista apenas com as faturas mais recentes
    return [fatura for _, fatura in faturas_por_cliente.values()]


def salvar_xmls_por_uc(faturas_dados: List[Dict[str, Any]], pasta_saida: str):
    """
    Converte as faturas em strings XML separadas e as salva na pasta de saída,
    agrupadas/nomeadas com base no CNPJ.
    """
    if not faturas_dados:
        print("Nenhuma fatura para salvar.")
        return

    # 1. Cria a pasta de saída se não existir
    Path(pasta_saida).mkdir(parents=True, exist_ok=True)

    # 2. Converte cada dicionário para sua string XML formatada, individualmente
    # O dicttoxml e manipulação de DOM é feita dentro desta função
    lista_xml_strings = converter_lote_para_xml_separado(faturas_dados)

    # 3. Salva cada XML, usando o CNPJ e o nome do arquivo original no nome.
    for i, xml_string in enumerate(lista_xml_strings):
        dados_fatura = faturas_dados[i]
        #print(dados_fatura)# Usa o índice para obter os metadados do dict original

        # Extrai CNPJ e Nome do Arquivo para o nome do arquivo XML
        #cnpj_consumidor = dados_fatura.get('cabecalho', {}).get('CnpjConsumidor')
        uc = dados_fatura.get('cabecalho', {}).get('CodigoCliente')
        nome_original_pdf = dados_fatura.get('@nome', f"arquivo_{i}.pdf")
        unidade_consumidora = uc.replace('\\', '').replace('/', '').replace('-', '')
        # O CNPJ é crucial para o agrupamento/nome
        #print(cnpj_consumidor)
        if not uc:
            print(f"Aviso: CNPJ não encontrado para o arquivo {nome_original_pdf}. Pulando salvamento.")
            continue

        # Limpa o nome do PDF (ex: 'fatura.pdf' -> 'fatura')
        nome_base = Path(nome_original_pdf).stem

        # Define o nome do arquivo: [CNPJ]-[NomeOriginalPDF].xml

        nome_arquivo_saida = f"{unidade_consumidora}.xml"
        caminho_saida = Path(pasta_saida) / nome_arquivo_saida

        try:
            with open(caminho_saida, 'w', encoding='utf-8') as f:
                f.write(xml_string)
            print(f"XML salvo com sucesso: {caminho_saida.name}")
        except Exception as e:
            print(f"Err ao salvar o arquivo {nome_arquivo_saida}: {e}")


def converter_lote_para_xml_separado(lote_dados: List[Dict[str, Any]]) -> List[str]:
    """
    Converte o lote de dicionários de faturas em uma lista de strings XML formatadas,
    onde cada string representa uma fatura (arquivo) individual.
    """
    lista_xml = []

    # 1. Itera sobre cada dicionário de dados (cada fatura)
    for dados_fatura in lote_dados:
        try:
            # 1.1. Converte o dicionário atual para XML
            # Use o custom_root adequado para a fatura individual
            xml_bytes = dicttoxml(
                dados_fatura,
                custom_root='NotaFiscalEnergia',  # O root para o XML de uma única fatura
                attr_type=False,
                item_func=lambda x: 'fatura_detalhe'
                # Um nome de tag interna temporária, se necessário, mas para um único dict, o root já basta.
            )

            dom = parseString(xml_bytes)
            root = dom.documentElement  # O elemento <NotaFiscalEnergia>

            keys_to_remove = []
            for child in list(root.childNodes):
                if child.nodeType == Node.ELEMENT_NODE and child.tagName == 'key':
                    key_name = child.getAttribute('name')
                    key_value = child.firstChild.nodeValue if child.firstChild else ""

                    # Adapte a lógica: os atributos 'id' e 'nome' devem ir para o <NotaFiscalEnergia>
                    if key_name == '@id':
                        keys_to_remove.append(child)
                    elif key_name == '@nome':
                        root.setAttribute('nome', key_value)
                        keys_to_remove.append(child)

            for key_node in keys_to_remove:
                root.removeChild(key_node)

            # 3. Ajuste para forçar tags vazias
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

            # 4. Formata e adiciona à lista
            xml_formatado = dom.toprettyxml(indent="  ")
            # Remove a declaração XML (a primeira linha) e espaços em branco
            xml_final = "\n".join(xml_formatado.split('\n')[1:]).strip()
            lista_xml.append(xml_final)

        except Exception as e:
            # Se der erro em um arquivo, imprime o erro e pula para o próximo
            print(f"Erro ao manipular/formatar XML para um dos arquivos: {e}")
            # Em caso de erro, você pode optar por adicionar a versão sem formatação ou apenas ignorar o arquivo
            lista_xml.append(
                xml_bytes.decode('utf-8') if 'xml_bytes' in locals() else f"ERRO NO PROCESSAMENTO: {e}")
            continue

    return lista_xml


def main():
    caminho_pasta = Path(PASTA_PDFS)
    arquivos_pdf = list(caminho_pasta.glob("*.pdf"))

    if not arquivos_pdf:
        print(f"Nenhum arquivo PDF encontrado na pasta: {PASTA_PDFS}")
        return

    todas_faturas = []

    for i, caminho_pdf in enumerate(arquivos_pdf, 1):
        print(f"Processando ({i}/{len(arquivos_pdf)}): {caminho_pdf.name}")

        resultado_plano, tributos_data, itens_tabela_brutos = processar_regiao_parallel(caminho_pdf)
        dados_extraidos = extrair_informacoes_estruturadas(resultado_plano, tributos_data, itens_tabela_brutos)

        dados_extraidos['@id'] = str(i)
        dados_extraidos['@nome'] = caminho_pdf.name

        todas_faturas.append(dados_extraidos)

    if todas_faturas:
        faturas_filtradas = filtrar_faturas_duplicadas(todas_faturas)
        salvar_xmls_por_uc(faturas_filtradas, PASTA_XML)
        print("\nProcessamento concluído. XMLs salvos na pasta:", PASTA_XML)


if __name__ == "__main__":
    main()