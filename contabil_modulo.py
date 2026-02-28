import os
import time
import re
import pandas as pd
import pdfplumber
import numpy as np
from datetime import datetime
from utils import remover_acentos, limpar_valor_universal


class ContabilModulo:
    def __init__(self, parent):
        self.parent = parent
        self.pasta_exe = parent.pasta_exe

        # Caminhos
        self.PASTA_PDF = os.path.join(self.pasta_exe, "arquivos_pdf")
        self.PASTA_EXCEL = os.path.join(self.pasta_exe, "arquivos_excel")
        self.PASTA_OFX = os.path.join(self.pasta_exe, "arquivos_ofx")
        self.KEYWORDS_AILOS = ['acredicoop', 'credicomin', 'credifoz', 'credelesc', 'credcrea', 'crevisc', 'acentra',
                               'viacredi', 'civia', 'unilos', 'evolua', 'transpocred']

        for p in [self.PASTA_PDF, self.PASTA_EXCEL, self.PASTA_OFX]:
            os.makedirs(p, exist_ok=True)

    def filtrar_arquivos(self, keywords):
        todos = [f for f in os.listdir(self.PASTA_PDF) if f.lower().endswith(".pdf")]
        return [f for f in todos if any(k in remover_acentos(f.lower()) for k in keywords)]

    def extrair_tabelas_pdfplumber(self, caminho_pdf):
        """Função auxiliar para extrair tabelas de todas as páginas usando PDFPlumber"""
        dados_totais = []
        try:
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    # extract_table tenta identificar a tabela automaticamente
                    tabela = page.extract_table()
                    if tabela:
                        for linha in tabela:
                            # Filtra linhas vazias ou None
                            if linha and any(linha):
                                dados_totais.append(linha)
            return dados_totais
        except Exception as e:
            print(f"Erro ao ler PDF {caminho_pdf}: {e}")
            return []

    # -------------------------------------------------------------------------
    # FLUXO BB V1 (Modelo Antigo/Padrão)
    # -------------------------------------------------------------------------
    def fluxo_bb_v1(self, log_func, finalizar_func):
        from processadores.banco_do_brasil import BBProcessorV1
        import time

        start = time.time()
        processador = BBProcessorV1(self.PASTA_PDF, self.PASTA_EXCEL)
        arquivos = self.filtrar_arquivos(['bb', 'brasil'])
        excels = []

        if not arquivos: log_func("Aviso: Nenhum PDF BB encontrado.", "erro")

        for arquivo in arquivos:
            try:
                resultado = processador.processar(arquivo, log_func)
                if resultado:
                    excels.append(resultado)
                    log_func(f"Sucesso: {resultado}", "sucesso")
            except Exception as e:
                log_func(f"Erro no fluxo BB V1: {e}", "erro")

        finalizar_func(excels)
        log_func(f"FIM BB V1 - {time.time() - start:.2f}s", "info")

    # -------------------------------------------------------------------------
    # FLUXO BB V2 (Novo Modelo Tabela)
    # -------------------------------------------------------------------------
    def fluxo_bb_v2(self, log_func, finalizar_func):
        from processadores.banco_do_brasil import BBProcessorV2
        import time

        start = time.time()
        processador = BBProcessorV2(self.PASTA_PDF, self.PASTA_EXCEL)
        arquivos = self.filtrar_arquivos(['bb', 'brasil'])
        excels = []

        if not arquivos: log_func("Aviso: Nenhum PDF BB encontrado.", "erro")

        for arquivo in arquivos:
            try:
                resultado = processador.processar(arquivo, log_func)
                if resultado:
                    excels.append(resultado)
                    log_func(f"Sucesso: {resultado}", "sucesso")
            except Exception as e:
                log_func(f"Erro no fluxo BB V2: {e}", "erro")

        finalizar_func(excels)
        log_func(f"FIM BB V2 - {time.time() - start:.2f}s", "info")

    # -------------------------------------------------------------------------
    # FLUXO SICOOB V1 (Celular - Layout Colorido)
    # -------------------------------------------------------------------------
    def fluxo_sicoob_celular(self, log_func, finalizar_func):
        from processadores.sicoob import SicoobCelularProcessor
        import time

        start = time.time()
        processador = SicoobCelularProcessor(self.PASTA_PDF, self.PASTA_EXCEL)
        arquivos = self.filtrar_arquivos(['sicoob']) # Ajuste a keyword conforme necessário
        excels = []

        if not arquivos: log_func("Aviso: Nenhum PDF Sicoob Celular encontrado.", "erro")

        for arquivo in arquivos:
            try:
                resultado = processador.processar(arquivo, log_func)
                if resultado:
                    excels.append(resultado)
                    log_func(f"Sucesso: {resultado}", "sucesso")
            except Exception as e:
                log_func(f"Erro no fluxo Sicoob Celular: {e}", "erro")

        finalizar_func(excels)
        log_func(f"FIM SICOOB CELULAR - {time.time() - start:.2f}s", "info")

    # -------------------------------------------------------------------------
    # FLUXO SICOOB V2 (Desktop)
    # -------------------------------------------------------------------------
    def fluxo_sicoob_pdf(self, log_func, finalizar_func):
        from processadores.sicoob import SicoobDesktopProcessor
        import time

        start = time.time()
        processador = SicoobDesktopProcessor(self.PASTA_PDF, self.PASTA_EXCEL)
        arquivos = self.filtrar_arquivos(['sicoob']) # Ajuste a keyword conforme necessário
        excels = []

        if not arquivos: log_func("Aviso: Nenhum PDF Sicoob Desktop encontrado.", "erro")

        for arquivo in arquivos:
            try:
                resultado = processador.processar(arquivo, log_func)
                if resultado:
                    excels.append(resultado)
                    log_func(f"Sucesso: {resultado}", "sucesso")
            except Exception as e:
                log_func(f"Erro no fluxo Sicoob Desktop: {e}", "erro")

        finalizar_func(excels)
        log_func(f"FIM SICOOB DESKTOP - {time.time() - start:.2f}s", "info")

    def fluxo_stone(self, log_func, finalizar_func):
        from processadores.stone import StoneProcessor
        import time

        start = time.time()
        processador = StoneProcessor(self.PASTA_PDF, self.PASTA_EXCEL)

        arquivos = self.filtrar_arquivos(['stone']) # Utilize a keyword correta (ex: self.KEYWORDS_STONE)
        excels = []

        if not arquivos:
            log_func("Aviso: Nenhum arquivo reconhecido como STONE na pasta de PDFs.", "erro")

        for arquivo in arquivos:
            try:
                resultado = processador.processar(arquivo, log_func)
                if resultado:
                    excels.append(resultado)
                    log_func(f"Sucesso: {resultado}", "sucesso")
            except Exception as e:
                log_func(f"Erro no processador Stone: {e}", "erro")

        finalizar_func(excels)
        log_func(f"FIM STONE - {time.time() - start:.2f}s", "info")

    def fluxo_pagbank(self, log_func, finalizar_func):
        from processadores.pagbank import PagbankProcessor
        import time

        start = time.time()
        processador = PagbankProcessor(self.PASTA_PDF, self.PASTA_EXCEL)

        # Utilize as keywords corretas do seu projeto para o PagBank/PagSeguro
        arquivos = self.filtrar_arquivos(['pagbank', 'pagseguro'])
        excels = []

        if not arquivos:
            log_func("Aviso: Nenhum arquivo reconhecido como PAGBANK na pasta de PDFs.", "erro")

        for arquivo in arquivos:
            try:
                resultado = processador.processar(arquivo, log_func)
                if resultado:
                    excels.append(resultado)
                    log_func(f"Sucesso: {resultado}", "sucesso")
            except Exception as e:
                log_func(f"Erro no processador PagBank: {e}", "erro")

        finalizar_func(excels)
        log_func(f"FIM PAGBANK - {time.time() - start:.2f}s", "info")


    def fluxo_ifood(self, log_func, finalizar_func):
        from processadores.ifood import IfoodProcessor
        import time

        start = time.time()
        processador = IfoodProcessor(self.PASTA_PDF, self.PASTA_EXCEL)

        arquivos = self.filtrar_arquivos(['ifood']) # Utilize a keyword correta (ex: self.KEYWORDS_IFOOD)
        excels = []

        if not arquivos:
            log_func("Aviso: Nenhum arquivo reconhecido como IFOOD na pasta de PDFs.", "erro")

        for arquivo in arquivos:
            try:
                resultado = processador.processar(arquivo, log_func)
                if resultado:
                    excels.append(resultado)
                    log_func(f"Sucesso: {resultado}", "sucesso")
            except Exception as e:
                log_func(f"Erro no processador iFood: {e}", "erro")

        finalizar_func(excels)
        log_func(f"FIM IFOOD - {time.time() - start:.2f}s", "info")


    def fluxo_santander_v1(self, log_func, finalizar_func):
        from processadores.santander import SantanderProcessorV1
        import time

        start = time.time()
        processador = SantanderProcessorV1(self.PASTA_PDF, self.PASTA_EXCEL)
        arquivos = self.filtrar_arquivos(['santander'])
        excels = []

        if not arquivos: log_func("Aviso: Nenhum PDF Santander V1 encontrado.", "erro")

        for arquivo in arquivos:
            try:
                resultado = processador.processar(arquivo, log_func)
                if resultado:
                    excels.append(resultado)
                    log_func(f"Sucesso: {resultado}", "sucesso")
            except Exception as e:
                log_func(f"Erro no fluxo Santander V1: {e}", "erro")

        finalizar_func(excels)
        log_func(f"FIM SANTANDER V1 - {time.time() - start:.2f}s", "info")

    # -------------------------------------------------------------------------
    # FLUXO SANTANDER V2 (Empresas)
    # -------------------------------------------------------------------------
    def fluxo_santander_v2(self, log_func, finalizar_func):
        from processadores.santander import SantanderProcessorV2
        import time

        start = time.time()
        processador = SantanderProcessorV2(self.PASTA_PDF, self.PASTA_EXCEL)
        arquivos = self.filtrar_arquivos(['santander'])
        excels = []

        if not arquivos: log_func("Aviso: Nenhum PDF Santander V2 encontrado.", "erro")

        for arquivo in arquivos:
            try:
                resultado = processador.processar(arquivo, log_func)
                if resultado:
                    excels.append(resultado)
                    log_func(f"Sucesso: {resultado}", "sucesso")
            except Exception as e:
                log_func(f"Erro no fluxo Santander V2: {e}", "erro")

        finalizar_func(excels)
        log_func(f"FIM SANTANDER V2 - {time.time() - start:.2f}s", "info")

    def fluxo_caixa_v1(self, log_func, finalizar_func):
        from processadores.caixa import CaixaProcessorV1
        import time
        start = time.time()
        processador = CaixaProcessorV1(self.PASTA_PDF, self.PASTA_EXCEL)
        arquivos = self.filtrar_arquivos(['caixa'])
        excels = []
        for arquivo in arquivos:
            resultado = processador.processar(arquivo, log_func)
            if resultado: excels.append(resultado)
        finalizar_func(excels)
        log_func(f"FIM CAIXA V1 - {time.time() - start:.2f}s", "info")

    def fluxo_caixa_v2_horizontal(self, log_func, finalizar_func):
        from processadores.caixa import CaixaProcessorV2Horizontal
        import time
        start = time.time()
        processador = CaixaProcessorV2Horizontal(self.PASTA_PDF, self.PASTA_EXCEL)
        arquivos = self.filtrar_arquivos(['caixa'])
        excels = []
        for arquivo in arquivos:
            resultado = processador.processar(arquivo, log_func)
            if resultado: excels.append(resultado)
        finalizar_func(excels)
        log_func(f"FIM CAIXA V2 HORIZONTAL - {time.time() - start:.2f}s", "info")

    def fluxo_caixa_v2_vertical(self, log_func, finalizar_func):
        from processadores.caixa import CaixaProcessorV2Vertical
        import time
        start = time.time()
        processador = CaixaProcessorV2Vertical(self.PASTA_PDF, self.PASTA_EXCEL)
        arquivos = self.filtrar_arquivos(['caixa'])
        excels = []
        for arquivo in arquivos:
            resultado = processador.processar(arquivo, log_func)
            if resultado: excels.append(resultado)
        finalizar_func(excels)
        log_func(f"FIM CAIXA V2 VERTICAL - {time.time() - start:.2f}s", "info")

    def fluxo_caixa_v3(self, log_func, finalizar_func):
        from processadores.caixa import CaixaProcessorV3
        import time
        start = time.time()
        processador = CaixaProcessorV3(self.PASTA_PDF, self.PASTA_EXCEL)
        arquivos = self.filtrar_arquivos(['caixa'])
        excels = []
        for arquivo in arquivos:
            resultado = processador.processar(arquivo, log_func)
            if resultado: excels.append(resultado)
        finalizar_func(excels)
        log_func(f"FIM CAIXA V3 - {time.time() - start:.2f}s", "info")

    def fluxo_sicredi(self, log_func, finalizar_func):
        from processadores.sicredi import SicrediProcessor
        import time

        start = time.time()
        processador = SicrediProcessor(self.PASTA_PDF, self.PASTA_EXCEL)

        # Ajuste a keyword para a que você utiliza no seu init, por exemplo self.KEYWORDS_SICREDI
        arquivos = self.filtrar_arquivos(['sicredi'])
        excels = []

        if not arquivos:
            log_func("Aviso: Nenhum arquivo reconhecido como SICREDI na pasta de PDFs.", "erro")

        for arquivo in arquivos:
            try:
                resultado = processador.processar(arquivo, log_func)
                if resultado:
                    excels.append(resultado)
                    log_func(f"Sucesso: {resultado}", "sucesso")
            except Exception as e:
                log_func(f"Erro no processador Sicredi: {e}", "erro")

        finalizar_func(excels)
        log_func(f"FIM SICREDI - {time.time() - start:.2f}s", "info")

    def fluxo_cresol(self, log_func, finalizar_func):
        from processadores.cresol import CresolProcessor
        import time

        start = time.time()
        processador = CresolProcessor(self.PASTA_PDF, self.PASTA_EXCEL)

        # Procura por ficheiros que tenham "cresol" no nome
        arquivos = self.filtrar_arquivos(['cresol'])
        excels = []

        if not arquivos:
            log_func("Aviso: Nenhum arquivo reconhecido como CRESOL na pasta de PDFs.", "erro")

        for arquivo in arquivos:
            try:
                resultado = processador.processar(arquivo, log_func)
                if resultado:
                    excels.append(resultado)
                    log_func(f"Sucesso: {resultado}", "sucesso")
            except Exception as e:
                log_func(f"Erro no processador Cresol: {e}", "erro")

        finalizar_func(excels)
        log_func(f"FIM CRESOL - {time.time() - start:.2f}s", "info")

    def fluxo_c6(self, log_msg, bridge_callback):
        import os
        import threading
        from processadores.c6 import C6Processor

        pasta_pdf = os.path.abspath("arquivos_pdf")
        pasta_excel = os.path.abspath("arquivos_excel")

        for pasta in [pasta_pdf, pasta_excel]:
            if not os.path.exists(pasta):
                os.makedirs(pasta)

        def processar():
            log_msg("Verificando arquivos na pasta 'arquivos_pdf'...", "info")

            arquivos = [f for f in os.listdir(pasta_pdf) if f.lower().endswith('.pdf') and 'c6' in f.lower()]

            if not arquivos:
                log_msg("Nenhum arquivo do C6 Bank (com 'c6' no nome) encontrado na pasta.", "erro")
                return

            processador = C6Processor(pasta_pdf, pasta_excel)
            excels_gerados = []

            for arquivo in arquivos:
                planilha = processador.processar(arquivo, log_msg)
                if planilha:
                    excels_gerados.append(planilha)

            if excels_gerados:
                log_msg(f"{len(excels_gerados)} arquivo(s) do C6 processado(s) com sucesso!", "sucesso", divisor=True)
                log_msg("Iniciando motor OFX...", "info")

                bridge_callback(excels_gerados)
            else:
                log_msg("Falha: Nenhum Excel foi gerado para o C6.", "erro")

        threading.Thread(target=processar, daemon=True).start()

    def fluxo_ailos(self, log_func, finalizar_func):
        from processadores.ailos import AilosProcessor
        import time

        start = time.time()
        processador = AilosProcessor(self.PASTA_PDF, self.PASTA_EXCEL)

        # Correção: Usando a sua lista de palavras-chave original
        arquivos = self.filtrar_arquivos(self.KEYWORDS_AILOS)
        excels = []

        # Trava de segurança para avisar se não achar nada
        if not arquivos:
            log_func("Aviso: Nenhum arquivo reconhecido como AILOS na pasta de PDFs.", "erro")
            log_func(f"Palavras-chave procuradas: {self.KEYWORDS_AILOS}", "info")

        for arquivo in arquivos:
            try:
                resultado = processador.processar(arquivo, log_func)
                if resultado:
                    excels.append(resultado)
                    log_func(f"Sucesso: {resultado}", "sucesso")
            except Exception as e:
                log_func(f"Erro no processador Ailos: {e}", "erro")

        finalizar_func(excels)
        log_func(f"FIM AILOS - {time.time() - start:.2f}s", "info")

    def gerar_ofx(self, log_func, lista_especifica=None):
        start_ofx = time.time();
        log_func("GERANDO OFX...", "info")
        arquivos = lista_especifica if lista_especifica else [f for f in os.listdir(self.PASTA_EXCEL) if
                                                              f.lower().endswith((".xlsx", ".xls"))]
        for arquivo in arquivos:
            try:
                df = pd.read_excel(os.path.join(self.PASTA_EXCEL, arquivo));
                df.columns = [str(col).strip().lower() for col in df.columns]
                h = f"OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\nENCODING:UTF-8\nCHARSET:UTF-8\nCOMPRESSION:NONE\n\n<OFX>\n<SIGNONMSGSRSV1>\n<SONRS>\n<STATUS>\n<CODE>0\n<SEVERITY>INFO\n</STATUS>\n<DTSERVER>{datetime.now().strftime('%Y%m%d%H%M%S')}\n<LANGUAGE>POR\n</SONRS>\n</SIGNONMSGSRSV1>\n\n<BANKMSGSRSV1>\n<STMTTRNRS>\n<TRNUID>1\n<STATUS>\n<CODE>0\n<SEVERITY>INFO\n</STATUS>\n\n<STMTRS>\n<CURDEF>BRL\n\n<BANKACCTFROM>\n<BANKID>0000\n<ACCTID>000000000\n<ACCTTYPE>CHECKING\n</BANKACCTFROM>\n\n<BANKTRANLIST>\n<DTSTART>20260101\n<DTEND>20261231\n";
                txs = ""
                for idx, row in df.iterrows():
                    val = limpar_valor_universal(row['valor']);
                    dt_o = str(row['data']);
                    dt = datetime.strptime(dt_o, '%d/%m/%Y').strftime('%Y%m%d') if '/' in dt_o else dt_o.replace('-',
                                                                                                                 '')[:8]
                    txs += f"<STMTTRN>\n<TRNTYPE>{'DEBIT' if val < 0 else 'CREDIT'}\n<DTPOSTED>{dt}\n<TRNAMT>{val:.2f}\n<FITID>{idx}\n<MEMO>{row['historico']}\n</STMTTRN>\n"
                f_out = f"</BANKTRANLIST>\n<LEDGERBAL>\n<BALAMT>0.00\n<DTASOF>{datetime.now().strftime('%Y%m%d%H%M%S')}\n</LEDGERBAL>\n</STMTRS>\n</STMTTRNRS>\n</BANKMSGSRSV1>\n</OFX>"
                with open(os.path.join(self.PASTA_OFX, os.path.splitext(arquivo)[0] + ".ofx"), "w",
                          encoding="utf-8") as f:
                    f.write(h + txs + f_out)
                log_func(f"OFX: {os.path.splitext(arquivo)[0]}.ofx", "sucesso")
            except Exception as e:
                log_func(f"Erro OFX {arquivo}: {e}", "erro")
        log_func(f"OFX CONCLUÍDO - {time.time() - start_ofx:.2f}s", "info")