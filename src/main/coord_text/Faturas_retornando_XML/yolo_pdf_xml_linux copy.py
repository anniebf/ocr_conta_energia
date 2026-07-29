import os
import requests
import base64
from dotenv import load_dotenv

def api_enviar_faturas():
    # Força a leitura do arquivo .env no diretório atual
    load_dotenv(override=True)

    url_base = os.getenv("URL_BASE")
    usuario = os.getenv("USER_BASE")
    senha = os.getenv("PASS_BASE")
    tenant_id = os.getenv("TENANT_ID")


    if not url_base or not usuario or not senha:
        print("[ERRO CRÍTICO] Variáveis de ambiente não foram carregadas do .env!")
        return

    # Monta o header Authorization manualmente em Base64 (padrão Basic Auth)
    credentials = f"{usuario}:{senha}"
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')

    headers = {
        'Content-Type': 'application/xml',
        'Authorization': f'Basic {encoded_credentials}',
        'tenantId': str(tenant_id)
    }

    pasta_xmls = r"C:\ocr_conta_energia\src\main\coord_text\Faturas_retornando_XML\xml"

    if not os.path.exists(pasta_xmls):
        print(f"[ERRO] A pasta '{pasta_xmls}' não existe.")
        return

    arquivos = [f for f in os.listdir(pasta_xmls) if f.lower().endswith('.xml')]

    if not arquivos:
        print(f"[AVISO] Nenhum arquivo .xml encontrado em: '{pasta_xmls}'.")
        return

    print(f"Iniciando envio de {len(arquivos)} arquivo(s)...")

    for arquivo in arquivos:
        caminho_completo = os.path.join(pasta_xmls, arquivo)
        
        try:
            with open(caminho_completo, 'r', encoding='utf-8') as file:
                xml_content = file.read()

            response = requests.post(
                url=url_base,
                data=xml_content.encode('utf-8'),
                headers=headers,
                timeout=30
            )

            if response.status_code in [200, 201]:
                print(f"[SUCESSO] Arquivo '{arquivo}' enviado com sucesso! Status: {response.status_code}")
            else:
                print(f"[ERRO] Falha ao enviar '{arquivo}'. Status: {response.status_code} | Resposta: {response.text}")

        except Exception as e:
            print(f"[EXCEÇÃO] Erro ao processar '{arquivo}': {e}")

if __name__ == "__main__":
    api_enviar_faturas()