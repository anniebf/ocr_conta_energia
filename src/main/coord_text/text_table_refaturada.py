import pdfplumber
import re


def extrair_texto_por_linhas(pdf_path, coordenadas, pagina=0):
    """Extrai texto por linhas de uma área específica do PDF"""
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


def gerar_csv_dados(linhas):
    """Gera dados CSV no formato solicitado"""
    cabecalho = "descricao;quant;preco unit com tributos;valor;pis/confins;base calc icms;porcent icms;icms;tarifa unit"
    linhas_csv = [cabecalho]

    for linha in linhas:
        texto_linha = linha['text']
        valores = []

        # Padrões de busca
        padroes = [
            (r'(Consumo.*?(?-i:KWH))', "Consumo", ["KWH"]),
            (r'(Energia.*?(?:KWH|UN|KW))', "Energia", ["KWH", "UN", "KW"]),
            (r'(Demanda.*?KW)', "Demanda", ["KW"]),
            (r'(Adic\. B\.)', "Adic. B.", []),
            (r'(Custo de Disponibilidade)', "Custo de Disponibilidade", []),
            (r'(.*TUSD[^\d]*(?:\d{2}/\d{4})?)', "TUSD", []),
            (r'(Ilum Pub)', "Ilum Pub", []),
            (r'(MULTA.*?\d{2}/\d{4})', "MULTA", []),
            (r'(JUROS DE.*?\d{2}/\d{4})', "JUROS DE", []),
            (r'(ATUALIZAÇÃO .*?\d{2}/\d{4})', "ATUALIZAÇÃO ", []),
            (r'(PARCELA.*?\d{2}/\d{4})', "PARCELA",[])
        ]

        for padrao, tipo, unidades in padroes:
            m = re.search(padrao, texto_linha, re.IGNORECASE)
            if m:
                descricao = m.group(1).strip()

                # Extrair valores após a unidade
                if unidades:
                    valores = extrair_valores_apos_unidade(texto_linha, unidades)
                else:
                    valores = re.findall(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+", texto_linha)

                # Formatar linha CSV
                if len(valores) == 8:
                    linha_csv = f"{descricao};{valores[0]};{valores[1]};{valores[2]};{valores[3]};{valores[4]};{valores[5]};{valores[6]};{valores[7]}"
                elif len(valores) == 5:
                    linha_csv = f"{descricao};;;;{valores[0]};{valores[1]};{valores[2]};{valores[3]};{valores[4]}"
                elif len(valores) == 1:
                    linha_csv = f"{descricao};;;;{valores[0]};;;;"
                else:
                    linha_csv = f"{descricao};;;;{valores[0]};{valores[1]};{valores[2]};{valores[3]};"

                linhas_csv.append(linha_csv)
                break

    return "\n".join(linhas_csv)


# Configurações
pdf_path = r"/src/resource/bkp pdfs/EMP 14 FL 01-2176118-NOTA FISCAL Nº 020.498.824 - Série 002 - OK.pdf"
coordenadas = [(21.7, 340.7), (434.4, 443.9)]
pagina = 0

# Extrair linhas
linhas = extrair_texto_por_linhas(pdf_path, coordenadas, pagina)

# Gerar CSV
csv_output = gerar_csv_dados(linhas)

# Mostrar resultado CSV
print(csv_output)