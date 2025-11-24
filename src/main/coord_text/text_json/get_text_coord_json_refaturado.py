import pdfplumber
import re
import json
import pandas as pd
from typing import Dict, Any, List, Tuple
from pathlib import Path
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from database.connect_oracle import retorno_cnpj_pdf

# CONFIGURAÇÃO
PASTA_PDFS = r"C:\bf_ocr\src\resource\pdf_refaturado"
ARQUIVO_EXCEL_SAIDA = r"C:\bf_ocr\src\resource\pdf_refaturado\faturas_processadas_botzin.xlsx"

# Regiões a serem extraídas
regioes = {
    "mais_a_cima": {"coordenadas": [(145.3, 4.1), (146.6, 54.3), (464.3, 54.3), (462.9, 6.8)],
                    "descricao": "Área mais acima"},
    "roteiro_tensao": {"coordenadas": [(43.5, 81.5), (40.7, 157.5), (319.1, 150.7), (306.9, 84.2)],
                       "descricao": "Roteiro e tensão"},
    "nota_fiscal_protocolo": {"coordenadas": [(419.5, 190.1), (418.1, 270.2), (552.5, 271.5), (549.8, 188.7)],
                              "descricao": "Nota fiscal e protocolo"},
    "nome_endereco": {"coordenadas": [(42.1, 160.3), (44.8, 201.0), (232.2, 196.9), (229.5, 163.0)],
                      "descricao": "Nome e endereço"},
    "codigo_cliente": {"coordenadas": [(236.3, 182.0), (237.7, 213.2), (331.4, 211.9), (334.1, 184.7)],
                       "descricao": "Código do cliente"},
    "ref_total_pagar": {"coordenadas": [(44.8, 260.7), (46.2, 285.2), (320.5, 282.5), (325.9, 252.6)],
                        "descricao": "Referência e total a pagar"},
    "tributos": {"coordenadas": [(434.4, 338.0), (556.6, 332.6), (434.4, 391.0), (559.3, 388.3)],
                 "descricao": "Tributos"},
    "tabela_itens": {"coordenadas": [(16.3, 334.0), (437.1, 545.7)],
                     "descricao": "Tabela de itens da fatura"},
    "cnpj": {"coordenadas": [(43.9, 216.4), (167.7, 235.6), (43.9, 236.4), (166.1, 214.8)],
                 "descricao": "cnpj"}
}



def calcular_retangulo(coordenadas):
    """Converte coordenadas em um retângulo (x0, top, x1, bottom)"""
    if len(coordenadas) == 2:  # Para a tabela de itens com formato diferente
        return (coordenadas[0][0], coordenadas[0][1], coordenadas[1][0], coordenadas[1][1])
    else:  # Para as outras regiões com 4 coordenadas
        x_coords = [coord[0] for coord in coordenadas]
        y_coords = [coord[1] for coord in coordenadas]
        return (min(x_coords), min(y_coords), max(x_coords), max(y_coords))


def extrair_texto_nas_coordenadas(pdf_path, retangulo):
    """Extrai texto mantendo informações de layout para melhor análise"""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pagina = pdf.pages[0]

            # Extrai palavras com suas coordenadas
            palavras = pagina.within_bbox(retangulo).extract_words(
                x_tolerance=3,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=True
            )

            if not palavras:
                return "Nenhum texto encontrado"

            # Agrupa palavras por linha baseado na coordenada y
            linhas = {}
            for palavra in palavras:
                y = round(palavra['top'])
                if y not in linhas:
                    linhas[y] = []
                linhas[y].append((palavra['x0'], palavra['text']))

            # Ordena as linhas e constrói o texto
            texto_ordenado = []
            for y in sorted(linhas.keys()):
                palavras_na_linha = sorted(linhas[y], key=lambda x: x[0])
                linha_texto = ' '.join([palavra[1] for palavra in palavras_na_linha])
                texto_ordenado.append(linha_texto)

            return '\n'.join(texto_ordenado)

    except Exception as e:
        return f"Erro: {str(e)}"


def extrair_texto_por_linhas(pdf_path, coordenadas, pagina=0):
    """Extrai texto por linhas de uma área específica do PDF (para tabela de itens)"""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pagina_pdf = pdf.pages[pagina]
            area = (
                coordenadas[0][0],
                coordenadas[0][1],
                coordenadas[1][0],
                coordenadas[1][1]
            )
            linhas = pagina_pdf.within_bbox(area).extract_text_lines()
            return linhas
    except Exception as e:
        print(f"Erro ao processar {pdf_path}: {e}")
        return []


def extrair_valores_apos_unidade(texto, unidades):
    """Extrai valores após as unidades KWH, UN ou KW"""
    for unidade in unidades:
        padrao = rf".*?{unidade}(.*)"
        match = re.search(padrao, texto, re.IGNORECASE)
        if match:
            parte_numerica = match.group(1).strip()
            return re.findall(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+", parte_numerica)
    return []


def processar_tabela_itens(linhas, pdf_path):
    """Processa a tabela de itens da fatura aplicando regras unificadas para descrição"""
    itens = []

    if not linhas:
        return itens

    for linha in linhas:
        texto_linha = linha['text'].strip()

        # Ignorar linhas sem números
        if not re.search(r"\d", texto_linha):
            continue

        # Ignorar linhas que começam com TOTAL:
        if texto_linha.upper().startswith("TOTAL:"):
            continue

        descricao, valores_str = extrair_descricao_valores(texto_linha)

        # Extrair valores numéricos
        valores = re.findall(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+", valores_str)

        item_data = {'descricao': descricao}

        # Preencher os valores nas colunas corretas
        if len(valores) >= 8:
            item_data.update({
                'quantidade': valores[0],
                'preco_unit_com_tributos': valores[1],
                'valor': valores[2],
                'pis_confins': valores[3],
                'base_calc_icms': valores[4],
                'porcent_icms': valores[5],
                'icms': valores[6],
                'tarifa_unit': valores[7]
            })
        elif len(valores) == 5:
            item_data.update({
                'valor': valores[0],
                'pis_confins': valores[1],
                'base_calc_icms': valores[2],
                'porcent_icms': valores[3],
                'icms': valores[4]
            })
        elif len(valores) == 1:
            item_data.update({
                'valor': valores[0]
            })
        elif valores:
            # Para outros casos, colocar o primeiro valor na coluna 'valor'
            item_data.update({
                'valor': valores[0]
            })

        itens.append(item_data)

    return itens


def extrair_descricao_valores(texto_linha: str):
    """
    Extrai a descrição e os valores de uma linha da fatura
    seguindo as regras:
      1. Se tiver unidade (KWH, KW, UN) → descrição vai até a unidade
      2. Se tiver data (xx/xxxx) → descrição vai até o primeiro número após a data
      3. Se não tiver data/unidade, mas tiver número → descrição vai até o primeiro número
      4. Caso contrário, descrição = linha inteira
    """
    unidades = ["KWH", "KW", "UN"]

    # Caso 1 → linha contém unidade
    for un in unidades:
        if un in texto_linha:
            partes = texto_linha.split(un, 1)
            descricao = partes[0].strip()
            valores = partes[1].strip() if len(partes) > 1 else ""
            return descricao, valores

    # Caso 2 → contém data (xx/xxxx)
    m_data = re.search(r"\b\d{2}/\d{4}\b", texto_linha)
    if m_data:
        # pega a parte até logo depois da data
        idx = m_data.end()
        resto = texto_linha[idx:]
        m_num = re.search(r"\d+", resto)
        if m_num:
            descricao = texto_linha[: idx + m_num.start()].strip()
            valores = resto[m_num.start():].strip()
            return descricao, valores

    # Caso 3 → não tem data/unidade, mas tem número
    m_num = re.search(r"\d+", texto_linha)
    if m_num:
        descricao = texto_linha[:m_num.start()].strip()
        valores = texto_linha[m_num.start():].strip()
        return descricao, valores

    # Caso 4 → fallback
    return texto_linha.strip(), ""


def processar_area_mais_acima(texto: str) -> Dict[str, Any]:
    """Processa a área mais acima"""
    linhas = texto.split('\n')
    resultado = {}

    if len(linhas) >= 2:
        resultado["distribuidora_energia"] = linhas[1].strip()

    if len(linhas) >= 4:
        # Extrai apenas o CEP (números de contato não serão usados)
        cep_match = re.search(r'\b\d{5}-?\d{3}\b', linhas[3])
        if cep_match:
            resultado["cep"] = cep_match.group()

    return resultado



def processar_cnpj(texto: str, nome_titular="") -> dict:
    resultado = {}
    linhas = texto.split('\n')

    num_cnpj = re.findall(r'\d', linhas[0])
    ult_num = (num_cnpj[-3:])
    prim_num = (num_cnpj[0])
    ult_num = ''.join(ult_num)
    #print(ult_num)

    print(linhas[1])
    num_insc = re.findall(r'\d+', linhas[1])
    num_insc = ''.join(num_insc)

    print(prim_num,ult_num,nome_titular,num_insc)
    cnpj = retorno_cnpj_pdf(prim_num,ult_num,nome_titular,num_insc)

    resultado = cnpj

    return resultado


def processar_roteiro_tensao(texto: str) -> Dict[str, Any]:
    """Processa roteiro e tensão"""
    linhas = [linha.strip() for linha in texto.split('\n') if linha.strip()]
    resultado = {}

    if len(linhas) >= 1:
        # Extrai roteiro completo (mantém números e hífens)
        roteiro_match = re.search(r'ROTEIRO:\s*([\d\s\-]+)', linhas[0], re.IGNORECASE)
        if roteiro_match:
            resultado["roteiro"] = roteiro_match.group(1).strip()
        else:
            # Fallback: pega apenas números se não encontrar "ROTEIRO:"
            roteiro_numeros = re.search(r'\b\d+\b', linhas[0])
            if roteiro_numeros:
                resultado["roteiro"] = roteiro_numeros.group()
            else:
                resultado["roteiro"] = linhas[0]

    if len(linhas) >= 2:
        # Extrai matrícula completa
        matricula_match = re.search(r'MATRÍCULA:\s*([\d\-]+)', linhas[1], re.IGNORECASE)
        if matricula_match:
            resultado["matricula"] = matricula_match.group(1).strip()
        else:
            # Fallback: pega apenas números
            matricula_match = re.search(r'\b\d+\b', linhas[1])
            if matricula_match:
                resultado["matricula"] = matricula_match.group()

    if len(linhas) >= 4:
        classificacao = []
        for i in range(3, min(6, len(linhas))):  # linhas 4, 5 e 6 (índices 3, 4, 5)
            if i < len(linhas):
                classificacao.append(linhas[i])
        texto_classificacao = ' '.join(classificacao)

        # Extrai informações específicas da classificação
        info_classificacao = {}

        # Extrai ligação (procura por TRIFASICO, MONOFASICO, BIFASICO)
        ligacao_match = re.search(r'(TRIFASICO|MONOFASICO|BIFASICO)', texto_classificacao, re.IGNORECASE)
        if ligacao_match:
            info_classificacao["ligacao"] = ligacao_match.group(1).upper()
        else:
            # Fallback: procura após "LIGAÇÃO:"
            ligacao_match = re.search(r'LIGAÇÃO:\s*([^/]+)', texto_classificacao, re.IGNORECASE)
            if ligacao_match:
                info_classificacao["ligacao"] = ligacao_match.group(1).strip()

        # Extrai grupo e subgrupo (B1, B2, B3, A1, etc.)
        grupo_subgrupo_match = re.search(r'/\s*([A-Z])(\d*)', texto_classificacao)
        if grupo_subgrupo_match:
            info_classificacao["grupo"] = grupo_subgrupo_match.group(1)
            if grupo_subgrupo_match.group(2):  # Se tem número
                info_classificacao["subgrupo"] = f"{grupo_subgrupo_match.group(1)}{grupo_subgrupo_match.group(2)}"
            else:
                info_classificacao["subgrupo"] = grupo_subgrupo_match.group(1)

        # Extrai classe (texto entre o subgrupo e a próxima barra ou fim)
        if 'subgrupo' in info_classificacao:
            # Procura o subgrupo seguido de texto até a próxima barra
            padrao_classe = re.search(
                rf'{info_classificacao["subgrupo"]}\s+([^/]+)',
                texto_classificacao,
                re.IGNORECASE
            )
            if padrao_classe:
                classe = padrao_classe.group(1).strip()
                # Remove possíveis barras no final
                classe = re.sub(r'/\s*$', '', classe).strip()
                info_classificacao["classe"] = classe

        resultado["classificacao"] = info_classificacao

    # Procura DISP em qualquer linha (não apenas na linha 7)
    for linha in linhas:
        disp_match = re.search(r'DISP\s*[:]?\s*(\d+)', linha, re.IGNORECASE)
        if disp_match:
            resultado["disp"] = disp_match.group(1)
            break
    else:
        resultado["disp"] = ""

    return resultado


def processar_nota_fiscal_protocolo(texto: str) -> Dict[str, Any]:
    """Processa nota fiscal e protocolo"""
    linhas = texto.split('\n')
    resultado = {}

    if len(linhas) >= 1:
        nf_match = re.search(r'\b\d{3}\.\d{3}\.\d{3}\b', linhas[0])
        if nf_match:
            resultado["numero_nota_fiscal"] = nf_match.group()

    if len(linhas) >= 2:
        data_match = re.search(r'\b\d{2}/\d{2}/\d{4}\b', linhas[1])
        if data_match:
            resultado["data_emissao"] = data_match.group()

    if len(linhas) >= 6:
        chave_texto = ' '.join(linhas[5:7])
        chave_match = re.search(r'\b\d{44}\b', chave_texto.replace(' ', ''))
        if chave_match:
            resultado["chave_acesso"] = chave_match.group()

    return resultado


def processar_nome_endereco(texto: str) -> Dict[str, Any]:
    """Processa nome e endereço"""
    linhas = texto.split('\n')
    resultado = {}

    if len(linhas) >= 1:
        resultado["nome_titular"] = linhas[0].strip()

    if len(linhas) >= 2:
        endereco = []
        for i in range(1, min(4, len(linhas))):
            if i < len(linhas):
                endereco.append(linhas[i].strip())
        resultado["endereco"] = ' '.join(endereco)

    return resultado


def processar_codigo_cliente(texto: str) -> Dict[str, Any]:
    """Processa código do cliente"""
    linhas = texto.split('\n')
    resultado = {}

    if len(linhas) >= 1:
        codigo_completo = re.search(r'[\d/]+-?\d*', linhas[0])
        if codigo_completo:
            resultado["codigo_cliente"] = codigo_completo.group()
        else:
            resultado["codigo_cliente"] = linhas[0].strip()

    return resultado


def processar_ref_total_pagar(texto: str) -> Dict[str, Any]:
    """Processa referência e total a pagar"""
    linhas = texto.split('\n')
    resultado = {}

    if linhas:
        linha_principal = linhas[0]

        ref_match = re.search(r'([A-Za-zçÇ]+)\s*/\s*(\d{4})', linha_principal, re.IGNORECASE)
        if ref_match:
            resultado["mes_ano_referencia"] = f"{ref_match.group(1)}/{ref_match.group(2)}"

        vencimento_match = re.search(r'\b\d{2}/\d{2}/\d{4}\b', linha_principal)
        if vencimento_match:
            resultado["data_vencimento"] = vencimento_match.group()

        total_match = re.search(r'R\$\s*([\d.,]+)', linha_principal)
        if total_match:
            resultado["total_pagar"] = total_match.group(1)

    return resultado


def processar_tributos(texto: str) -> Dict[str, Any]:
    """Processa tributos"""
    linhas = texto.split('\n')
    resultado = {}

    if len(linhas) >= 2:
        pis_texto = ' '.join(linhas[0:2])
        pis_valores = re.findall(r'[\d.,]+', pis_texto)
        if len(pis_valores) >= 3:
            resultado["PIS"] = {
                "base_calculo": pis_valores[0],
                "aliquota": pis_valores[1],
                "valor": pis_valores[2]
            }

    if len(linhas) >= 3:
        cofins_valores = re.findall(r'[\d.,]+', linhas[2])
        if len(cofins_valores) >= 3:
            resultado["COFINS"] = {
                "base_calculo": cofins_valores[0],
                "aliquota": cofins_valores[1],
                "valor": cofins_valores[2]
            }

    if len(linhas) >= 4:
        icms_valores = re.findall(r'[\d.,]+', linhas[3])
        if len(icms_valores) >= 3:
            resultado["ICMS"] = {
                "base_calculo": icms_valores[0],
                "aliquota": icms_valores[1],
                "valor": icms_valores[2]
            }

    return resultado


def processar_regiao_parallel(nome, texto, resultado_parcial):
    """Processa uma região individual em thread"""
    try:
        if nome == "mais_a_cima":
            return "informacoes_superiores", processar_area_mais_acima(texto)
        elif nome == "roteiro_tensao":
            return "roteiro_tensao", processar_roteiro_tensao(texto)
        elif nome == "nota_fiscal_protocolo":
            return "nota_fiscal", processar_nota_fiscal_protocolo(texto)
        elif nome == "nome_endereco":
            return "cliente", processar_nome_endereco(texto)
        elif nome == "codigo_cliente":
            return "codigo_cliente", processar_codigo_cliente(texto)
        elif nome == "ref_total_pagar":
            return "pagamento", processar_ref_total_pagar(texto)
        elif nome == "tributos":
            return "tributos", processar_tributos(texto)
        elif nome == "cnpj":
            # CNPJ precisa esperar o cliente estar pronto
            nome_titular = resultado_parcial.get('cliente', {}).get('nome_titular', '')
            return "cnpj", processar_cnpj(texto, nome_titular)
    except Exception as e:
        return nome, {"erro": f"Erro no processamento: {str(e)}", "texto_bruto": texto}


def extrair_informacoes_json(pdf_path: str) -> Dict[str, Any]:
    """Extrai todas as informações e retorna como JSON com threading"""
    resultado_final = {}

    # Extrair todos os textos primeiro (fora das threads)
    textos_regioes = {}
    for nome, info in regioes.items():
        if nome == "tabela_itens":
            continue  # Tabela será processada separadamente

        retangulo = calcular_retangulo(info["coordenadas"])
        texto = extrair_texto_nas_coordenadas(pdf_path, retangulo)

        if texto.startswith("Erro") or texto == "Nenhum texto encontrado":
            resultado_final[nome] = {"erro": texto}
        else:
            textos_regioes[nome] = texto

    # Processar regiões independentes em paralelo
    regioes_independentes = ["mais_a_cima", "roteiro_tensao", "nota_fiscal_protocolo",
                             "nome_endereco", "codigo_cliente", "ref_total_pagar", "tributos"]

    # Dicionário temporário para resultados parciais (usado pelo CNPJ)
    resultado_parcial = resultado_final.copy()

    with ThreadPoolExecutor(max_workers=4) as executor:
        # Enviar todas as tarefas independentes para execução
        future_to_regiao = {}

        for nome in regioes_independentes:
            if nome in textos_regioes:  # Só processa se tem texto válido
                future = executor.submit(processar_regiao_parallel, nome, textos_regioes[nome], resultado_parcial)
                future_to_regiao[future] = nome

        # Coletar resultados conforme ficam prontos
        for future in concurrent.futures.as_completed(future_to_regiao):
            nome = future_to_regiao[future]
            try:
                chave, resultado = future.result()
                resultado_final[chave] = resultado
                resultado_parcial[chave] = resultado  # Atualiza parcial para o CNPJ
            except Exception as e:
                resultado_final[nome] = {"erro": str(e)}

    # Processar CNPJ (depende do cliente)
    if "cnpj" in textos_regioes and "cliente" in resultado_final:
        try:
            nome_titular = resultado_final.get('cliente', {}).get('nome_titular', '')
            resultado_final["cnpj"] = processar_cnpj(textos_regioes["cnpj"], nome_titular)
        except Exception as e:
            resultado_final["cnpj"] = {"erro": f"Erro no processamento: {str(e)}",
                                       "texto_bruto": textos_regioes["cnpj"]}

    # PASSO 4: Processar tabela de itens (fora do threading por ser complexa)
    if "tabela_itens" in regioes:
        try:
            linhas = extrair_texto_por_linhas(pdf_path, regioes["tabela_itens"]["coordenadas"])
            resultado_final["itens_fatura"] = processar_tabela_itens(linhas, pdf_path)
        except Exception as e:
            resultado_final["itens_fatura"] = {"erro": f"Erro na tabela: {str(e)}"}

    return resultado_final


def criar_dataframe_consolidado(dados_todos_pdfs: List[Tuple[str, Dict[str, Any]]]) -> pd.DataFrame:
    """Cria um DataFrame consolidado com todos os dados dos PDFs"""
    linhas_consolidadas = []

    for caminho_pdf, dados in dados_todos_pdfs:
        linha = {}

        # Informações básicas do arquivo
        linha['caminho_arquivo'] = str(caminho_pdf)
        linha['nome_arquivo'] = caminho_pdf.name

        # Informações gerais
        info_gerais = dados.get('informacoes_superiores', {})
        linha.update({f'{k}': v for k, v in info_gerais.items()})

        # Roteiro e tensão
        roteiro = dados.get('roteiro_tensao', {})
        linha.update({f'{k}': v for k, v in roteiro.items() if k != 'classificacao'})

        classificacao = roteiro.get('classificacao', {})
        linha.update({f'{k}': v for k, v in classificacao.items()})

        # Nota fiscal
        nota_fiscal = dados.get('nota_fiscal', {})
        linha.update({f'nota_fiscal_{k}': v for k, v in nota_fiscal.items()})

        # Cliente
        cliente = dados.get('cliente', {})
        linha.update({f'{k}': v for k, v in cliente.items()})

        # Código do cliente
        codigo_cliente = dados.get('codigo_cliente', {})
        linha.update({f'{k}': v for k, v in codigo_cliente.items()})

        # Pagamento
        pagamento = dados.get('pagamento', {})
        linha.update({f'{k}': v for k, v in pagamento.items()})

        # Tributos (colunas separadas para PIS, COFINS, ICMS)
        tributos = dados.get('tributos', {})
        for tributo, valores in tributos.items():
            if isinstance(valores, dict):
                for chave, valor in valores.items():
                    linha[f'tributo_{tributo.lower()}_{chave}'] = valor

        # Itens da fatura (cada item em colunas separadas)
        itens = dados.get('itens_fatura', [])
        for i, item in enumerate(itens):
            for chave, valor in item.items():
                linha[f'{chave}'] = valor

        linhas_consolidadas.append(linha)

    return pd.DataFrame(linhas_consolidadas)



def main():
    caminho_pasta = Path(PASTA_PDFS)
    arquivos_pdf = list(caminho_pasta.glob("*.pdf"))

    if not arquivos_pdf:
        print(f"Nenhum arquivo PDF encontrado na pasta: {PASTA_PDFS}")
        return

    print(f"Encontrados {len(arquivos_pdf)} arquivos PDF para processar")
    print(f"{'=' * 80}")

    dados_todos_pdfs = []

    # Processa cada arquivo PDF
    for i, caminho_pdf in enumerate(arquivos_pdf, 1):
        print(f"Processando ({i}/{len(arquivos_pdf)}): {caminho_pdf.name}")


        # Extrai informações estruturadas
        dados_extraidos = extrair_informacoes_json(caminho_pdf)

        # Converte para JSON com formatação
        nome_titular = dados_extraidos['cliente']['nome_titular']

        json_output = json.dumps(dados_extraidos, ensure_ascii=False, indent=2)

        print("DADOS EXTRAÍDOS (JSON):")
        print(json_output)

        # Salva em arquivo (opcional)
        #nome_arquivo_saida = os.path.splitext(os.path.basename(CAMINHO_PDF))[0] + "_dados.json"
        #caminho_saida = os.path.join(os.path.dirname(CAMINHO_PDF), nome_arquivo_saida)

        #with open(caminho_saida, 'w', encoding='utf-8') as f:
        #    f.write(json_output)

        #print(f"\nDados salvos em: {caminho_saida}")


if __name__ == "__main__":
    main()