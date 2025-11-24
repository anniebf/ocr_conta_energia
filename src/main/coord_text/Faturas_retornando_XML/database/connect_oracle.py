import oracledb
import pandas
import os
from dotenv import load_dotenv
load_dotenv()

usernameBd = os.getenv("usernameBd")
passwordBd= os.getenv("passwordBd")
dsn = os.getenv("dsn")

connectionBd = oracledb.connect(user=usernameBd, password=passwordBd, dsn=dsn)
cursor = connectionBd.cursor()

def retorno_cnpj_pdf(prim_num,ult_num,nome_titular,num_insc):

    cursor.execute(fr"""
        SELECT m0_CGC 
        FROM PROTHEUS11.sigaemp
        WHERE m0_CGC LIKE '{prim_num}%{ult_num}'
        AND M0_NOMECOM LIKE '%{nome_titular}%'
        AND M0_INSC LIKE '{num_insc}%'
        """)

    cnpj_atual = cursor.fetchall()

    return cnpj_atual

if __name__ == '__main__':
    retorno_cnpj_pdf('', '', '', '')