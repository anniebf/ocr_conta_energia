import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import io
from email.mime.base import MIMEBase
from email import encoders
import csv
from datetime import datetime
import os
from dotenv import load_dotenv
load_dotenv()

server_smtp = os.getenv("server_smtp")
port = os.getenv("port")
sender_mail = os.getenv("sender_mail")
password = os.getenv("password")

destinatarios = [ "hianny.urt@bomfuturo.com.br","LUIS.NUNES@bomfuturo.com.br"]

def UnidadesComErro(dicUc):
    csv_buffer = io.StringIO()
    csv_writer = csv.writer(csv_buffer, delimiter=';')
    csv_writer.writerow(['Unidade Consumidora', 'Erro Completo'])


    for chave, valor in dicUc.items():
        csv_writer.writerow([chave, str(valor)])


    html_lista = "<ul>"
    quant_uc = len(dicUc)

    for chave, valor in dicUc.items():
        valor_str = str(valor)
        # Resumo do erro
        if "Erro" in valor_str:
            erro_resumido = valor_str.split(":", 2)[0] + " - " + valor_str.split("mensagem\":\"")[1].split("\"")[
                0] if "mensagem" in valor_str else valor_str[:80] + "..."
        else:
            erro_resumido = valor_str[:80] + "..." if len(valor_str) > 80 else valor_str

        html_lista += f'''
        <li style="margin-bottom: 15px;">
            <div><strong>Unidade Consumidora:</strong> {chave}</div>
            <div><strong>Descrição do Erro:</strong> {erro_resumido}</div>
        </li>
        '''

    html_lista += "</ul>"

    try:
        data = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")

        subject = fr"API DOWNLOADS DE FATURAS DE ENERGIA"
        body = f"""\
        <h1>Unidades consumidoras que não conseguiram ser baixadas</h1>
        <p>Quantidade de U/C com erro: {quant_uc}</p>
        <p>###########################################################</p>
        <p></p>
        {html_lista}
        <p>###########################################################</p>
        <p>Email gerado por Python -- host: so-dcc-jobpyhml -- caminho: /python_bf/api_energisa/download_faturas.py</p>
        """

        message = MIMEMultipart()
        message["From"] = sender_mail
        message["To"] = ", ".join(destinatarios)
        message["Subject"] = subject
        # Corpo do e-mail em HTML
        message.attach(MIMEText(body, "html"))

        # Anexar o arquivo CSV
        csv_buffer.seek(0)
        csv_data = csv_buffer.getvalue()

        anexo = MIMEBase('application', 'octet-stream')
        anexo.set_payload(csv_data.encode('utf-8'))
        encoders.encode_base64(anexo)
        anexo.add_header(
            'Content-Disposition',
            f'attachment; filename="erros_faturas_{data}.csv"'
        )
        message.attach(anexo)

        # Anexo (CSV)
        server = smtplib.SMTP(server_smtp, port)
        server.starttls()
        server.login(sender_mail, password)
        server.sendmail(sender_mail, destinatarios, message.as_string())
        server.quit()
        print('--------------------------------')
        print('Email de finalizacao enviado com sucesso')
        print('--------------------------------')
    except Exception as e:
        print('--------------------------------')
        print('ERRO AO ENVIAR O EMAIL DE FINALIZAÇÃO')
        print('ERRO: ', e)
        print('--------------------------------')
    finally:
        csv_buffer.close()

    return
if "__main__" == __name__:
    dicUc = {'65120171-3': 'Erro 412: {"infos":{"codigo":"CONDICAO_INVALIDA","mensagem":"Não foi possível gerar a fatura com os dados desta requisição pois não foi encontrado um Boleto com os dados disponiveis.","categoria":"OK"},"mensagem":"Não foi possível gerar a fatura com os dados desta requisição pois não foi encontrado um Boleto com os dados disponiveis.","errored":true}', '6643517-6': 'Erro 500: {"infos":{"type":"Buffer","data":[60,72,84,77,76,62,60,72,69,65,68,62,10,60,84,73,84,76,69,62,73,110,116,101,114,110,97,108,32,83,101,114,118,101,114,32,69,114,114,111,114,60,47,84,73,84,76,69,62,10,60,47,72,69,65,68,62,60,66,79,68,89,62,10,60,72,49,62,73,110,116,101,114,110,97,108,32,83,101,114,118,101,114,32,69,114,114,111,114,32,45,32,82,101,97,100,60,47,72,49,62,10,84,104,101,32,115,101,114,118,101,114,32,101,110,99,111,117,110,116,101,114,101,100,32,97,110,32,105,110,116,101,114,110,97,108,32,101,114,114,111,114,32,111,114,32,109,105,115,99,111,110,102,105,103,117,114,97,116,105,111,110,32,97,110,100,32,119,97,115,32,117,110,97,98,108,101,32,116,111,10,99,111,109,112,108,101,116,101,32,121,111,117,114,32,114,101,113,117,101,115,116,46,60,80,62,10,82,101,102,101,114,101,110,99,101,38,35,51,50,59,38,35,51,53,59,51,38,35,52,54,59,99,100,97,98,51,55,49,55,38,35,52,54,59,49,55,54,49,56,53,54,48,53,51,38,35,52,54,59,51,99,101,102,99,55,56,49,10,60,80,62,104,116,116,112,115,38,35,53,56,59,38,35,52,55,59,38,35,52,55,59,101,114,114,111,114,115,38,35,52,54,59,101,100,103,101,115,117,105,116,101,38,35,52,54,59,110,101,116,38,35,52,55,59,51,38,35,52,54,59,99,100,97,98,51,55,49,55,38,35,52,54,59,49,55,54,49,56,53,54,48,53,51,38,35,52,54,59,51,99,101,102,99,55,56,49,60,47,80,62,10,60,47,66,79,68,89,62,60,47,72,84,77,76,62,10]},"errored":true}', '62103515-9': 'Erro 412: {"infos":{"codigo":"CONDICAO_INVALIDA","mensagem":"Não foi possível gerar a fatura com os dados desta requisição pois não foi encontrado um Boleto com os dados disponiveis.","categoria":"OK"},"mensagem":"Não foi possível gerar a fatura com os dados desta requisição pois não foi encontrado um Boleto com os dados disponiveis.","errored":true}', '63359145-4': 'Erro 412: {"infos":{"codigo":"CONDICAO_INVALIDA","mensagem":"Não foi possível gerar a fatura com os dados desta requisição pois não foi encontrado um Boleto com os dados disponiveis.","categoria":"OK"},"mensagem":"Não foi possível gerar a fatura com os dados desta requisição pois não foi encontrado um Boleto com os dados disponiveis.","errored":true}'}
    UnidadesComErro(dicUc)