import requests
import msal
import json
import os
import time
import re
from curl_cffi import requests as curl_requests
from dotenv import load_dotenv
from datetime import datetime
import logging

load_dotenv()

mes_atual = datetime.now().month
ano_atual = datetime.now().year
if mes_atual < 10:
    mes_atual = f'0{mes_atual}'

logging.basicConfig(
    level=logging.INFO,  # Pode ser DEBUG, INFO, WARNING, ERROR, CRITICAL
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(fr"./logs/{datetime.now().strftime('%d-%m-%yyyy')}_downloads_faturas_energisa.log", encoding='utf-8'),
        logging.StreamHandler()  # Mostra também no console
    ]
)

error_uc={}

class EnergisaAutomacao:
    BASE_URL = "https://servicos.energisa.com.br"

    def __init__(self, documento):
        self.documento = documento
        self.session = curl_requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Content-Type': 'application/json'
        })
        self.access_token = None
        self.udk_token = None
        self.utk_token = None
        self.refresh_token = None
        self.retk_token = None
        self.unidades_encontradas = []
        self.login_completo = False

    def executar_login_automatico(self):
        logging.info("Iniciando login automático...")

        if not self._obter_cookies_e_token():
            logging.error("Falha ao obter cookies e token.")
            return False

        unidade_login = {"codigoEmpresaWeb": "6", "cdc": "3359145", "digitoVerificador": "4", "posicao": "0"}
        logging.info(f"Usando unidade para login: UC {unidade_login['cdc']}")

        if not self._solicitar_codigo_com_unidade(unidade_login):
            logging.error("Falha ao solicitar código de segurança.")
            return False

        codigo = self._buscar_codigo_seguranca()
        if not codigo:
            logging.error("Código de segurança não encontrado.")
            return False

        if self._validar_codigo(codigo):
            self.login_completo = True
            logging.info("Login concluído com sucesso.")
            self.unidades_encontradas = self.consultar_unidades_consumidoras()
            return True

        logging.warning("Validação de código falhou.")
        return False

    def _obter_cookies_e_token(self):
        try:
            self.session.get(f"{self.BASE_URL}/login", timeout=15, impersonate="chrome110")
            response = self.session.get(f"{self.BASE_URL}/api/auth", timeout=15, impersonate="chrome110")
            auth_data = response.json()
            if auth_data.get("autenticated"):
                self.access_token = auth_data.get('accessTokenEnergisa')
                logging.info("Token de acesso obtido")
                return True
        except Exception as e:
            logging.error(f"Falha na autenticação: {e}")
        return False

    def _solicitar_codigo_com_unidade(self, unidade):
        payload = {"ate": self.access_token, "udk": "", "utk": "", "refreshToken": "", "retk": ""}
        try:
            response = self.session.post(
                f"{self.BASE_URL}/api/autenticacao/CodigoSeguranca/EmailPorUC",
                params=unidade, json=payload, timeout=15, impersonate="chrome110"
            )
            logging.info("Código solicitado")
            return response.ok
        except Exception as e:
            logging.error(f"Falha ao solicitar código: {e}")
            return False

    def _buscar_codigo_seguranca(self, max_tentativas=8, intervalo=10, espera_inicial=30):
        logging.info(f"Aguardando {espera_inicial}s para email...")
        time.sleep(espera_inicial)

        graph_token = self._obter_token_graph()
        if not graph_token:
            return None

        for tentativa in range(max_tentativas):
            logging.info(f"Tentativa {tentativa + 1}/{max_tentativas}...")
            emails = self._buscar_emails(graph_token)

            for email in emails:
                if self._is_email_valido(email):
                    codigo = self._extrair_codigo_html(email.get('body', {}).get('content', ''))
                    if codigo:
                        logging.info(f"CÓDIGO ENCONTRADO: {codigo}")
                        return codigo

            if tentativa < max_tentativas - 1:
                time.sleep(intervalo)
        return None

    def _obter_token_graph(self):
        try:
            logging.debug("Obtendo token do Microsoft Graph...")
            autoridade = f"https://login.microsoftonline.com/{os.getenv('GRAPH_TENANT_ID')}"
            aplicacao = msal.ConfidentialClientApplication(
                client_id=os.getenv('GRAPH_CLIENT_ID'),
                authority=autoridade,
                client_credential=os.getenv('GRAPH_CLIENT_SECRET')
            )
            resultado = aplicacao.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
            token = resultado.get('access_token')
            if token:
                logging.info("Token Graph obtido com sucesso.")
            else:
                logging.error(f"Falha ao obter token Graph: {resultado}")
            return token
        except Exception as e:
            logging.exception("Erro ao obter token Graph")
            return None

    def _buscar_emails(self, token):
        try:
            headers = {'Authorization': f'Bearer {token}'}
            url = f"https://graph.microsoft.com/v1.0/users/{os.getenv('BOT_USER_EMAIL')}/mailFolders/{os.getenv('BOT_EMAIL_FOLDER')}/messages"
            params = {'$select': 'id,subject,receivedDateTime,body,from', '$orderby': 'receivedDateTime desc',
                      '$top': 5}
            response = requests.get(url, headers=headers, params=params)
            return response.json().get('value', [])
        except:
            return []

    def _is_email_valido(self, email):
        remetente = email.get('from', {}).get('emailAddress', {}).get('address', '').lower()
        assunto = email.get('subject', '').lower()
        return (remetente == "sistemas@sac.energisa.com.br".lower() and
                "código de segurança da energisa".lower() in assunto)

    def _extrair_codigo_html(self, html):
        digitos = re.findall(r'<td><div[^>]*><p[^>]*>(\d)</p></div></td>', html)
        if digitos and len(digitos) >= 4:
            return ''.join(digitos[:4])

        texto = re.sub(r'<[^>]+>', ' ', html)
        texto = re.sub(r'\s+', ' ', texto)
        match = re.search(r'código de segurança[^\d]*(\d)\s*(\d)\s*(\d)\s*(\d)', texto, re.IGNORECASE)
        return ''.join(match.groups()) if match else None

    def _validar_codigo(self, codigo):
        params = {"doc": self.documento, "codigoSegurancaRecebido": codigo}
        try:
            response = self.session.post(
                f"{self.BASE_URL}/api/autenticacao/UsuarioClienteEnergisa/Autenticacao/PorCpfCnpj",
                params=params, timeout=15, impersonate="chrome110"
            )
            dados = response.json()
            infos = dados.get("infos", {})

            if not dados.get("errored") or "logado com sucesso" in infos.get("message", "").lower():
                self.udk_token = infos.get("udk", "")
                self.utk_token = infos.get("utk", "")
                self.refresh_token = infos.get("refreshToken", "")
                self.retk_token = infos.get("retk", "")
                logging.info(" Token da Energisa validado")
                return True
        except Exception as e:
            logging.info(f" Falha na validação: {e}")
        return False

    def consultar_unidades_consumidoras(self):
        if not self.login_completo:
            return []

        url = f"{self.BASE_URL}/api/usuarios/UnidadeConsumidora?doc={self.documento}"
        payload = {
            "ate": self.access_token,
            "udk": self.udk_token,
            "utk": self.utk_token,
            "refreshToken": self.refresh_token,
            "retk": self.retk_token
        }

        try:
            logging.info("Consultando unidades...")
            response = self.session.post(url, json=payload, timeout=15, impersonate="chrome110")
            resposta = response.json()

            unidades_data = resposta.get("infos", [])

            logging.info(f" {len(unidades_data)} unidades encontradas:")

            unidades_mapeadas = []
            for uc in unidades_data:
                unidade = {
                    'cdc': uc.get('numeroUc'),
                    'digitoVerificadorCdc': uc.get('digitoVerificador'),
                    'codigoEmpresaWeb': uc.get('codigoEmpresaWeb'),
                    'endereco': f"{uc.get('endereco', '')}, {uc.get('complemento', '')}",
                    'nome': uc.get('nomeTitular'),
                    'cidade': uc.get('nomeMunicipio'),
                    'situacao': 'ATIVA' if uc.get('ucAtiva') else 'INATIVA'
                }
                if unidade['situacao'] == 'INATIVA':
                    pass
                else:
                    unidades_mapeadas.append(unidade)
                    logging.info(f"  UC: {unidade['codigoEmpresaWeb']}/{unidade['cdc']}-{unidade['digitoVerificadorCdc']} | {unidade['nome']} | STATUS: {unidade['situacao']}")


            return unidades_mapeadas

        except Exception as e:
            logging.error(f"Erro ao consultar unidades: {e}")
            return []

    def baixar_fatura_direto(self, cdc, digito_verificador, codigo_empresa, mes=mes_atual, ano=ano_atual):
        """Baixa fatura diretamente sem consultar primeiro (igual ao seu código que funciona)"""
        if not self.login_completo or not cdc:
            return False

        logging.info(f"\nINICIANDO DOWNLOAD DA FATURA PARA CDC {cdc}...")
        # Paylod usando as mesma chamadas do postman
        payload = {
            "codigoEmpresaWeb": codigo_empresa,
            "cdc": cdc,
            "digitoVerificadorCdc": digito_verificador,
            "ano": ano,
            "mes": mes,
            "cdcRed": None,
            "fatura": 0,
            "ate": self.access_token,
            "udk": self.udk_token,
            "utk": self.utk_token,
            "refreshToken": self.refresh_token,
            "retk": self.retk_token
        }

        # Headers iguais ao usados no postman
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36',
            'Content-Type': 'application/json',
            'Cookie': "; ".join([f"{k}={v}" for k, v in self.session.cookies.get_dict().items()])
        }

        try:
            response = self.session.post(
                f"{self.BASE_URL}/api/clientes/SegundaVia/Download",
                json=payload,
                headers=headers,
                timeout=30,
                impersonate="chrome110"
            )

            logging.info(f"Status: {response.status_code}")

            if response.status_code == 200:
                if response.content.startswith(b'%PDF'):
                    # Salva o PDF
                    nome_arquivo = fr"faturas/Data_{ano}-{mes:02d}_UC_{codigo_empresa}{cdc}{digito_verificador}.pdf"
                    os.makedirs("../faturas", exist_ok=True)

                    with open(nome_arquivo, 'wb') as f:
                        f.write(response.content)

                    logging.info(f"PDF salvo: {nome_arquivo}")
                    return True
                else:
                    logging.error("Resposta não é PDF válido")
                    logging.error(f"Conteúdo: {response.text[:200]}...")
                    #error_uc.append(fr"{codigo_empresa}{cdc}-{digito_verificador}")
                    error_uc[fr"{codigo_empresa}{cdc}-{digito_verificador}"] = f"Erro {response.status_code}: {response.text}"
            else:
                logging.info(f"Erro {response.status_code}: {response.text}")
                error_uc[fr"{codigo_empresa}{cdc}-{digito_verificador}"] = f"Erro {response.status_code}: {response.text}"

        except Exception as e:
            logging.error(f"Erro no download: {e}")

        return False


    def baixar_faturas_para_todas_unidades(self, mes=mes_atual, ano=ano_atual):
        """Tenta baixar faturas para todas as unidades encontradas"""
        if not self.login_completo:
            return False

        logging.info(f"\nBAIXANDO FATURAS DE {mes}/{ano} PARA TODAS AS UNIDADES...")

        if not self.unidades_encontradas:
            logging.info("Nenhuma unidade disponível")
            return False

        total_baixadas = 0

        for unidade in self.unidades_encontradas:
            cdc = unidade['cdc']

            # Tentar baixar fatura diretamente
            if self.baixar_fatura_direto(
                    cdc,
                    unidade['digitoVerificadorCdc'],
                    unidade['codigoEmpresaWeb'],
                    mes,
                    ano
            ):
                total_baixadas += 1

        logging.info(f"\nTOTAL: {total_baixadas}/{len(self.unidades_encontradas)} faturas baixadas")

        return total_baixadas > 0


if __name__ == "__main__":
    automacao = EnergisaAutomacao(documento="10425282000122")

    if automacao.executar_login_automatico():
        logging.info("Login concluído! Iniciando download das faturas...")
        automacao.baixar_faturas_para_todas_unidades(mes=mes_atual, ano=ano_atual)
        logging.info(f"U/C que não baixaram a fatura: {error_uc}")

        with open("./log/UC_Com_Erro.txt", 'wb') as uctxt:
            uctxt.write(error_uc)
    else:
        logging.error("Falha no login.")

#Classe EnergisaAutomacao - encapsula o comportamento e os dados para interagir com o site da energisa | a classe define as características (atributos) e as ações (métodos) que um objeto deve ter
#Metodos/Funções - Os métodos são as funções definidas dentro da classe. Eles definem o que o objeto pode fazer.
#Atributos/dados -o número do documento/ os tokens de autenticacao (access_token, udk_token, etc.)/ e a sessão de requisicoes (self.session) | atributos são variáveis que armazenam o estado de um objeto

#Session() = representa uma Sessão HTTP persistente
#o HTTP (o protocolo da Web) é "sem estado". Isso significa que, se você fizer duas requisições consecutivas (por exemplo, primeiro para a página de login e depois para a página de faturas), o servidor não tem como saber que as duas requisições vieram do mesmo usuário.
#O self.session é um objeto que armazena e reutiliza automaticamente dados importantes em várias requisições, simulando a continuidade de um navegador
#