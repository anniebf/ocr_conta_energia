import os
import xml.etree.ElementTree as ET

def buscar_cliente_nos_xmls(caminho_pasta, codigo_cliente):
    # Lista para guardar os arquivos que contêm o cliente
    arquivos_encontrados = []
    
    # Verifica se a pasta realmente existe
    if not os.path.exists(caminho_pasta):
        print(f"Erro: A pasta '{caminho_pasta}' não foi encontrada.")
        return
    
    # Percorre todos os arquivos da pasta
    for nome_arquivo in os.listdir(caminho_pasta):
        # Garante que só vai ler arquivos com extensão .xml
        if nome_arquivo.endswith('.xml') or nome_arquivo.endswith('.XML'):
            caminho_completo = os.path.join(caminho_pasta, nome_arquivo)
            
            try:
                # Carrega e analisa o arquivo XML
                tree = ET.parse(caminho_completo)
                root = tree.getroot()
                
                # Procura por QUALQUE tag chamada 'CodigoCliente' dentro do XML
                # O './/' faz uma busca profunda em toda a árvore do XML
                encontrou_no_arquivo = False
                for elemento in root.findall('.//CodigoCliente'):
                    if elemento.text == codigo_cliente:
                        encontrou_no_arquivo = True
                        break # Se achou uma vez no arquivo, já é suficiente
                
                if encontrou_no_arquivo:
                    arquivos_encontrados.append(nome_arquivo)
                    print(f"✔ Encontrado no arquivo: {nome_arquivo}")
                        
            except ET.ParseError:
                print(f"❌ Erro ao ler o arquivo {nome_arquivo}: XML inválido ou mal formatado.")
            except Exception as e:
                print(f"❌ Erro inesperado no arquivo {nome_arquivo}: {e}")

    # Resumo da busca
    print("\n--- Resultado Final ---")
    if arquivos_encontrados:
        print(f"O cliente '{codigo_cliente}' foi encontrado em {len(arquivos_encontrados)} arquivo(s) XML:")
        for arq in arquivos_encontrados:
            print(f"- {arq}")
    else:
        print(f"Nenhum arquivo XML com <CodigoCliente>{codigo_cliente}</CodigoCliente> foi encontrado.")

# --- CONFIGURAÇÃO ---
# Substitua pelo caminho da sua pasta de XMLs
PASTA_DOS_XMLS = fr"/python/coord_text/Faturas_retornando_XML/xmls" 
CODIGO_PROCURADO = "90506501793"

# Executa a busca
buscar_cliente_nos_xmls(PASTA_DOS_XMLS, CODIGO_PROCURADO)