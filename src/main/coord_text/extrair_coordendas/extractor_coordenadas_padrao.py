import pdfplumber
import fitz  # PyMuPDF
import pygame
import sys
import os
from PIL import Image
import tempfile

"""
ESSE CODIGO ABRE UM PDF QUE ME PERMITE PEGAR AS COORDENADAS DELE
"""



# CONFIGURAÇÃO: Altere este caminho para o seu arquivo PDF
CAMINHO_PDF =r"C:\bf_ocr\src\main\api\faturas\EMP 16 FL 1008081 - 4668543 -NOTA FISCAL Nº 044.606.418 - Série 001 OK.pdf"


def mostrar_pdf_com_coordenadas(pdf_path):
    try:
        # Verificar se o arquivo existe
        if not os.path.exists(pdf_path):
            print(f"Erro: Arquivo não encontrado - {pdf_path}")
            return

        # Abrir o PDF com PyMuPDF para renderizar as páginas
        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            print("Erro: O PDF não contém páginas")
            return

        page = doc[0]  # Vamos trabalhar com a primeira página

        # Primeiro inicializar o Pygame
        pygame.init()

        # Obter informações da tela DEPOIS de inicializar o Pygame
        screen_info = pygame.display.Info()
        max_width = screen_info.current_w - 100  # Margem de 100 pixels
        max_height = screen_info.current_h - 100  # Margem de 100 pixels

        # Calcular fator de escala mantendo a proporção
        pdf_width, pdf_height = page.rect.width, page.rect.height
        scale_x = max_width / pdf_width
        scale_y = max_height / pdf_height
        scale = min(scale_x, scale_y)

        # Ajustar manualmente o scale como float
        scale = float(scale) * 1.6

        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat)

        # Salvar temporariamente a imagem renderizada
        temp_img_path = tempfile.mktemp(suffix='.png')
        pix.save(temp_img_path)

        # Carregar a imagem do PDF
        img = pygame.image.load(temp_img_path)
        screen_width, screen_height = img.get_size()
        screen = pygame.display.set_mode((screen_width, screen_height))
        pygame.display.set_caption(
            "Clique em qualquer lugar no PDF para obter as coordenadas. Pressione ESC para sair.")

        # Cor de fundo para área around da imagem (se houver)
        background = pygame.Surface((screen_width, screen_height))
        background.fill((240, 240, 240))

        # Variável para armazenar as últimas coordenadas
        ultimas_coordenadas = None

        running = True
        clock = pygame.time.Clock()

        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    # Obter a posição do mouse
                    mouse_x, mouse_y = pygame.mouse.get_pos()

                    # Converter coordenadas da tela para coordenadas do PDF
                    pdf_x = mouse_x / scale
                    pdf_y = mouse_y / scale

                    # Armazenar as últimas coordenadas
                    ultimas_coordenadas = (pdf_x, pdf_y, mouse_x, mouse_y)

                    # Imprimir as coordenadas no console
                    coord_text = f"Coordenadas: PDF({pdf_x:.1f}, {pdf_y:.1f}), Tela({mouse_x}, {mouse_y})"
                    print(coord_text)

            # Limpar a tela
            screen.blit(background, (0, 0))
            screen.blit(img, (0, 0))

            # Desenhar instruções
            font = pygame.font.Font(None, 24)
            instrucoes = [
                "Clique em qualquer lugar no PDF para obter as coordenadas",
                "Pressione ESC para sair",
                "Clique com o botão direito para limpar as coordenadas"
            ]

            for i, texto in enumerate(instrucoes):
                text_surface = font.render(texto, True, (0, 0, 0))
                screen.blit(text_surface, (10, 10 + i * 25))

            # Mostrar as últimas coordenadas se existirem
            if ultimas_coordenadas:
                pdf_x, pdf_y, mouse_x, mouse_y = ultimas_coordenadas
                coord_text = f"Últimas coordenadas: PDF({pdf_x:.1f}, {pdf_y:.1f})"
                text_surface = font.render(coord_text, True, (255, 0, 0))
                screen.blit(text_surface, (10, screen_height - 30))

                # Desenhar um círculo vermelho na posição clicada
                pygame.draw.circle(screen, (255, 0, 0), (mouse_x, mouse_y), 5)

            pygame.display.flip()
            clock.tick(30)  # 30 FPS

        pygame.quit()
        doc.close()
        # Remover arquivo temporário se existir
        if os.path.exists(temp_img_path):
            os.remove(temp_img_path)

    except Exception as e:
        print(f"Erro ao processar o PDF: {str(e)}")
        import traceback
        traceback.print_exc()
        # Garantir que o pygame é fechado mesmo em caso de erro
        pygame.quit()


if __name__ == "__main__":
    # Verificar se o caminho do PDF foi definido
    if CAMINHO_PDF == "caminho/para/seu/arquivo.pdf":
        print("Por favor, altere a variável CAMINHO_PDF no código para apontar para o seu arquivo PDF.")
        print("Exemplo: CAMINHO_PDF = \"C:/Users/SeuNome/Documentos/meu_arquivo.pdf\"")
        sys.exit(1)

    mostrar_pdf_com_coordenadas(CAMINHO_PDF)