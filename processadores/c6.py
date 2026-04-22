import os
import re
import fitz  # PyMuPDF nativo (Sem Java!)
from datetime import datetime
from base_processor import BaseProcessor


class C6Processor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "C6"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo C6 Bank (Modo Nativo sem Java): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            linhas = []
            ano_atual = str(datetime.now().year)

            # =========================================================
            # 1. AGRUPAMENTO DE LINHAS E EXTRAÇÃO DO ANO BASE
            # =========================================================
            for page in doc:
                # Procura o ano no texto livre da página
                texto_pagina = page.get_text("text")
                match_ano = re.search(r'\d{2}/\d{2}/(\d{4})', texto_pagina)
                if match_ano:
                    ano_atual = match_ano.group(1)

                words = page.get_text("words")
                if not words: continue

                # Ordena as palavras verticalmente e depois horizontalmente
                words.sort(key=lambda w: (w[1], w[0]))

                linha_atual = []
                y_ref = None

                # Reconstrói as linhas aglutinando palavras com a mesma altura (y)
                for w in words:
                    if y_ref is None:
                        linha_atual.append(w)
                        y_ref = w[1]
                    elif abs(w[1] - y_ref) <= 4:  # Tolerância de alinhamento vertical
                        linha_atual.append(w)
                    else:
                        linha_atual.sort(key=lambda x: x[0])
                        linhas.append(" ".join([x[4] for x in linha_atual]))
                        linha_atual = [w]
                        y_ref = w[1]

                if linha_atual:
                    linha_atual.sort(key=lambda x: x[0])
                    linhas.append(" ".join([x[4] for x in linha_atual]))

            if not linhas:
                log_func(f"Aviso: Nenhuma linha útil encontrada em {arquivo}", "erro")
                return None

            registros = []

            # =========================================================
            # 2. MÁQUINA DE ESTADOS CONTÍNUA DO C6
            # =========================================================
            for linha in linhas:
                linha_str = linha.strip()
                if not linha_str: continue

                linha_up = linha_str.upper()

                # Filtra cabeçalhos da tabela e lixo comum
                if "SALDO" in linha_up and "DIA" in linha_up: continue
                if "DATA" in linha_up and "HISTÓRICO" in linha_up: continue
                if "VALOR" in linha_up and "R$" in linha_up: continue

                # PASSO 1: Capturar a DATA (Sempre no início da linha ex: 15/04)
                match_data = re.search(r'^([0-3]\d/[0-1]\d)', linha_str)
                if not match_data:
                    continue  # Não começou com data? Ignora a linha

                data_dia_mes = match_data.group(1)
                data_formatada = f"{data_dia_mes}/{ano_atual}"

                # Remove a data capturada da string para limparmos o histórico
                linha_str = linha_str[match_data.end():].strip()

                # Se houver uma data repetida colada (Data contábil), remove também
                if re.search(r'^([0-3]\d/[0-1]\d)', linha_str):
                    linha_str = re.sub(r'^([0-3]\d/[0-1]\d)', '', linha_str).strip()

                # PASSO 2: Capturar o VALOR (Sempre no final da linha)
                # Procura por R$, RS ou apenas o número (positivo ou negativo) no fim da frase
                match_valor = re.search(r'(-?(?:R\$|RS)?\s*\d{1,3}(?:\.\d{3})*,\d{2})\s*$', linha_str, re.IGNORECASE)

                if not match_valor:
                    # Falha de segurança: Tenta formato com ponto final nos centavos (se o PDF vier bugado)
                    match_valor = re.search(r'(-?(?:R\$|RS)?\s*\d{1,3}(?:,\d{3})*\.\d{2})\s*$', linha_str,
                                            re.IGNORECASE)

                if match_valor:
                    valor_str_raw = match_valor.group(1)
                    # Remove o valor do fim da string, o que sobrar é o histórico puro!
                    linha_str = linha_str[:match_valor.start()].strip()
                else:
                    continue  # Linha sem valor financeiro no fim não é transação

                # Limpeza cirúrgica do valor
                val_clean_str = valor_str_raw.upper().replace("R$", "").replace("RS", "").strip()
                eh_negativo = "-" in val_clean_str
                val_clean_str = val_clean_str.replace("-", "").strip()

                # Converte usando o seu método nativo do BaseProcessor
                val_num = self.limpar_valor(val_clean_str)
                if val_num == 0:
                    continue

                # PASSO 3: Guardar Histórico
                historico_final = linha_str.strip()
                if not historico_final:
                    historico_final = "LANCAMENTO C6"

                registros.append({
                    "DATA": data_formatada,
                    "HISTORICO": self.remover_acentos(historico_final).upper(),
                    "VALOR": -abs(val_num) if eh_negativo else abs(val_num),
                    "TIPO": "DEBITO" if eh_negativo else "CREDITO"
                })

            # =========================================================
            # 3. CONSTRUÇÃO DO EXCEL
            # =========================================================
            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0]
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar C6 {arquivo}: {e}", "erro")
            return None