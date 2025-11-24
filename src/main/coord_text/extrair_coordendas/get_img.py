import fitz  # PyMuPDF
from PIL import Image
import os


"""
ESSE CODIGO PEGAS AS COORDENADAS E FAZ UMPRINT E RETRNA UM PNG NA PASTA IMAGENS_RETORNADAS PARA CONFIRMACAO 
"""

# CONFIGURAÇÃO: Altere este caminho para o seu arquivo PDF
CAMINHO_PDF = r"C:\bf_ocr\src\main\api\faturas\EMP 16 FL 1008081 - 4668543 -NOTA FISCAL Nº 044.606.418 - Série 001 OK.pdf"
PASTA_SAIDA = r"C:\bf_ocr\src\main\coord_text\imagens_retornadas"

# Definir as regiões a serem extraídas
regioes = {
    "mais_a_cima": {
        "coordenadas": [
            (65.7, 20.0),   # PDF(X, Y) - Canto 1
            (66.8, 46.8),   # PDF(X, Y) - Canto 2
            (214.9, 47.9),  # PDF(X, Y) - Canto 3
            (218.2, 24.5)   # PDF(X, Y) - Canto 4
        ],
        "descricao": "Área mais acima"
    },
    "codigo_cliente": {
        "coordenadas": [
            (181.5, 85.7),
            (182.6, 110.2),
            (270.6, 85.7),
            (270.6, 108.0)
        ],
        "descricao": "Código do cliente"
    },
    "referencia": {
        "coordenadas": [
            (12.2, 138.1),
            (15.6, 160.3),
            (270.6, 140.3),
            (270.6, 162.6)
        ],
        "descricao": "Referência"
    },
    "cnpj": {
        "coordenadas": [
            (5.5, 126.5),
            (8.3, 139.4),
            (107.3, 126.5),
            (99.0, 141.2)
        ],
        "descricao": "CNPJ"
    },
    "nome_endereco": {
        "coordenadas": [
            (3.9, 77.0),
            (2.9, 125.7),
            (176.3, 80.9),
            (174.4, 122.8)
        ],
        "descricao": "Nome e endereço"
    },
    "numero_nota_fiscal": {
        "coordenadas": [
            (96.4, 168.5),
            (95.5, 226.0),
            (272.8, 170.5),
            (269.9, 229.9)
        ],
        "descricao": "Número da nota fiscal"
    },
    "itens": {
        "coordenadas": [
            (3.9, 371.2),
            (1.0, 469.6),
            (290.3, 368.3),
            (289.3, 465.7)
        ],
        "descricao": "Itens da fatura"
    },
    "tributos": {
        "coordenadas": [
            (143.2, 493.9),
            (143.2, 529.0),
            (276.7, 493.0),
            (273.8, 530.0)
        ],
        "descricao": "Tributos"
    }
}
#(21.7, 346.2), (434.4, 340.7), (433.1, 439.8), (23.1, 443.9)  cordenadas dos itens do refaturados

def calcular_retangulo_regiao(coordenadas):
    """
    Calcula o retângulo que engloba todas as coordenadas fornecidas
    """
    x_coords = [coord[0] for coord in coordenadas]
    y_coords = [coord[1] for coord in coordenadas]

    x0 = min(x_coords)
    y0 = min(y_coords)
    x1 = max(x_coords)
    y1 = max(y_coords)

    return fitz.Rect(x0, y0, x1, y1)


def extrair_regioes_pdf(pdf_path, pasta_saida):
    """
    Extrai as regiões específicas do PDF e salva como imagens PNG
    """
    try:
        # Verificar se o arquivo existe
        if not os.path.exists(pdf_path):
            print(f"Erro: Arquivo não encontrado - {pdf_path}")
            return False

        # Criar pasta de saída se não existir
        if not os.path.exists(pasta_saida):
            os.makedirs(pasta_saida)

        # Abrir o PDF
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            print("Erro: O PDF não contém páginas")
            return False

        # Processar a primeira página
        pagina = doc[0]

        print(f"Processando PDF: {os.path.basename(pdf_path)}")
        print(f"Tamanho da página: {pagina.rect.width:.1f} x {pagina.rect.height:.1f} pontos")
        print("-" * 50)

        # Extrair cada região
        for nome_regiao, info in regioes.items():
            coordenadas = info["coordenadas"]
            descricao = info["descricao"]

            # Calcular o retângulo da região
            retangulo = calcular_retangulo_regiao(coordenadas)

            print(f"Extraindo: {descricao}")
            print(f"Coordenadas: {retangulo}")

            # Criar uma matriz de transformação para a região
            mat = fitz.Matrix(2, 2)  # Zoom 2x para melhor qualidade

            # Obter o pixmap da região
            pix = pagina.get_pixmap(matrix=mat, clip=retangulo)

            # Converter para imagem PIL
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # Salvar a imagem
            caminho_imagem = os.path.join(pasta_saida, f"{nome_regiao}.png")
            img.save(caminho_imagem, "PNG")

            print(f"Salvo em: {caminho_imagem}")
            print(f"Tamanho da imagem: {img.width} x {img.height} pixels")
            print()

        # Fechar o documento
        doc.close()

        print("Extração concluída com sucesso!")
        print(f"Imagens salvas na pasta: {pasta_saida}")
        return True

    except Exception as e:
        print(f"Erro ao processar o PDF: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def criar_pdf_com_regioes(pasta_imagens, nome_pdf_saida):
    """
    Cria um PDF com todas as regiões extraídas
    """
    try:
        # Listar todas as imagens PNG na pasta
        imagens = [f for f in os.listdir(pasta_imagens) if f.endswith('.png')]

        if not imagens:
            print("Nenhuma imagem encontrada para criar o PDF")
            return False

        # Criar um novo documento PDF
        doc = fitz.open()

        # Adicionar cada imagem como uma página do PDF
        for imagem_nome in sorted(imagens):
            caminho_imagem = os.path.join(pasta_imagens, imagem_nome)

            # Criar uma nova página (tamanho A6 para as imagens menores)
            pagina = doc.new_page(width=420, height=595)  # A6 em pontos (1/4 de A4)

            # Calcular posição para centralizar a imagem
            img = Image.open(caminho_imagem)
            img_width, img_height = img.size

            # Converter pixels para pontos (72 DPI)
            img_width_pt = img_width * 72 / 96
            img_height_pt = img_height * 72 / 96

            # Calcular escala para caber na página
            scale_x = 400 / img_width_pt
            scale_y = 550 / img_height_pt
            scale = min(scale_x, scale_y)

            # Calcular posição
            x = (420 - img_width_pt * scale) / 2
            y = (595 - img_height_pt * scale) / 2

            # Inserir a imagem
            pagina.insert_image(
                fitz.Rect(x, y, x + img_width_pt * scale, y + img_height_pt * scale),
                filename=caminho_imagem
            )

            # Adicionar título
            nome_regiao = imagem_nome.replace('.png', '').replace('_', ' ').title()
            pagina.insert_text((50, 30), nome_regiao, fontsize=16, color=(0, 0, 0))

        # Salvar o PDF
        doc.save(nome_pdf_saida)
        doc.close()

        print(f"PDF criado com sucesso: {nome_pdf_saida}")
        return True

    except Exception as e:
        print(f"Erro ao criar PDF: {str(e)}")
        return False


if __name__ == "__main__":
    # Verificar se o caminho do PDF foi definido
    if CAMINHO_PDF == "caminho/para/seu/arquivo.pdf":
        print("Por favor, altere a variável CAMINHO_PDF no código para apontar para o seu arquivo PDF.")
        print("Exemplo: CAMINHO_PDF = \"C:/Users/SeuNome/Documentos/meu_arquivo.pdf\"")
        exit(1)

    # Extrair as regiões como imagens PNG
    sucesso = extrair_regioes_pdf(CAMINHO_PDF, PASTA_SAIDA)

    if sucesso:
        # Criar um PDF com todas as regiões
        pdf_saida = os.path.join(PASTA_SAIDA, "todas_regioes.pdf")
        criar_pdf_com_regioes(PASTA_SAIDA, pdf_saida)

        print("\n" + "=" * 50)
        print("RESUMO DA EXTRACTION:")
        print("=" * 50)
        for nome_regiao, info in regioes.items():
            coordenadas = info["coordenadas"]
            retangulo = calcular_retangulo_regiao(coordenadas)
            print(f"{info['descricao']}:")
            print(f"  Arquivo: {nome_regiao}.png")
            print(f"  Área: {retangulo.width:.1f} x {retangulo.height:.1f} pontos")
            print()