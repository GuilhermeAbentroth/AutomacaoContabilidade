import os
import re
from datetime import datetime


class CaixaOfxSanitizer:
    def __init__(self, pasta_ofx_entrada, pasta_ofx_saida):
        self.pasta_entrada = pasta_ofx_entrada
        self.pasta_saida = pasta_ofx_saida
        os.makedirs(self.pasta_saida, exist_ok=True)

    def sanitizar(self, arquivo_nome, log_func):
        caminho_in = os.path.join(self.pasta_entrada, arquivo_nome)
        log_func(f"Sanitizando OFX Caixa: {arquivo_nome}")

        try:
            with open(caminho_in, 'r', encoding='latin-1') as f:
                conteudo = f.read()

            # 1. Extrair todas as transações <STMTTRN>
            transacoes = re.findall(r'<STMTTRN>(.*?)</STMTTRN>', conteudo, re.DOTALL)

            if not transacoes:
                log_func(f"Aviso: Nenhuma transação encontrada em {arquivo_nome}", "erro")
                return None

            # 2. Montar o novo conteúdo
            novo_ofx = self._gerar_cabecalho()

            for tr in transacoes:
                # Extrair campos básicos usando regex
                tipo = re.search(r'<TRNTYPE>(.*?)(?:<|$)', tr).group(1)
                data = re.search(r'<DTPOSTED>(.*?)(?:<|$)', tr).group(1)[:8]  # Pega apenas YYYYMMDD
                valor = re.search(r'<TRNAMT>(.*?)(?:<|$)', tr).group(1)
                id_trans = re.search(r'<FITID>(.*?)(?:<|$)', tr).group(1)
                memo = re.search(r'<MEMO>(.*?)(?:<|$)', tr).group(1)

                novo_ofx += f"""<STMTTRN>
<TRNTYPE>{tipo}
<DTPOSTED>{data}
<TRNAMT>{valor}
<FITID>{id_trans}
<MEMO>{memo}
</STMTTRN>
"""

            novo_ofx += self._gerar_rodape()

            # 3. Salvar o arquivo limpo
            nome_saida = f"LIMPO_{arquivo_nome}"
            caminho_out = os.path.join(self.pasta_saida, nome_saida)

            with open(caminho_out, 'w', encoding='utf-8') as f:
                f.write(novo_ofx)

            return nome_saida

        except Exception as e:
            log_func(f"Erro ao processar OFX {arquivo_nome}: {e}", "erro")
            return None

    def _gerar_cabecalho(self):
        return f"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:UTF-8
CHARSET:UTF-8
COMPRESSION:NONE

<OFX>
<SIGNONMSGSRSV1>
<SONRS>
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<DTSERVER>{datetime.now().strftime('%Y%m%d%H%M%S')}
<LANGUAGE>POR
</SONRS>
</SIGNONMSGSRSV1>
<BANKMSGSRSV1>
<STMTTRNRS>
<TRNUID>1
<STATUS>
<CODE>0
<SEVERITY>INFO
</STATUS>
<STMTRS>
<CURDEF>BRL
<BANKACCTFROM>
<BANKID>0104
<ACCTID>00000000
<ACCTTYPE>CHECKING
</BANKACCTFROM>
<BANKTRANLIST>
<DTSTART>20260101
<DTEND>20261231
"""

    def _gerar_rodape(self):
        return """</BANKTRANLIST>
<LEDGERBAL>
<BALAMT>0.00
<DTASOF>20260101
</LEDGERBAL>
</STMTRS>
</STMTTRNRS>
</BANKMSGSRSV1>
</OFX>"""