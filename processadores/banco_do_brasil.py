import os
import re
import pdfplumber
import pandas as pd
from base_processor import BaseProcessor


# ==========================================
# CLASSE 1: BB MODELO 1 (Leitura Geométrica)
# ==========================================
class BBProcessorV1(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "BB_V1"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo BB V1 (Geométrico): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)
        registros = []
        current_entry = None
        stop_proc = False

        try:
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    if stop_proc: break
                    words = page.extract_words(x_tolerance=5, y_tolerance=3)
                    if not words: continue

                    linhas = []
                    curr_l = [words[0]]
                    for i in range(1, len(words)):
                        if abs(words[i]['top'] - curr_l[-1]['top']) < 3:
                            curr_l.append(words[i])
                        else:
                            linhas.append(curr_l)
                            curr_l = [words[i]]
                    linhas.append(curr_l)

                    for lw in linhas:
                        lw.sort(key=lambda x: x['x0'])
                        txt_orig = " ".join([w['text'] for w in lw])
                        txt_norm = self.remover_acentos(txt_orig).upper().strip()

                        # Condições de Parada
                        if any(t in txt_norm for t in
                               ["INFORMACOES ADICIONAIS", "TOTAL APLICACOES", "RESUMO", "OBSERVACOES"]):
                            stop_proc = True
                            break

                        # Ignora Saldos
                        if any(t in txt_norm for t in
                               ["SALDO ANTERIOR", "SALDO DO DIA", "S A L D O", "DATA HISTORICO"]):
                            if current_entry: registros.append(current_entry)
                            current_entry = None
                            continue

                        # Busca Data e Valor (+) ou (-)
                        m_data = re.search(r"(\d{2}/\d{2}/\d{4})", txt_orig)
                        m_valor = re.search(r"([\d.]+,\d{2})\s*\(([+-])\)", txt_orig)

                        if m_data:
                            if current_entry: registros.append(current_entry)
                            current_entry = {
                                "DATA": m_data.group(1),
                                "HISTORICO": txt_orig.replace(m_data.group(1), "").strip(),
                                "VALOR": 0.0,
                                "TIPO": ""
                            }
                            if m_valor:
                                v_num = self.limpar_valor(m_valor.group(1))
                                current_entry["VALOR"] = -abs(v_num) if m_valor.group(2) == "-" else abs(v_num)
                                current_entry["TIPO"] = "DEBITO" if m_valor.group(2) == "-" else "CREDITO"
                                current_entry["HISTORICO"] = current_entry["HISTORICO"].replace(m_valor.group(0),
                                                                                                "").strip()

                        elif m_valor and current_entry:
                            v_num = self.limpar_valor(m_valor.group(1))
                            current_entry["VALOR"] = -abs(v_num) if m_valor.group(2) == "-" else abs(v_num)
                            current_entry["TIPO"] = "DEBITO" if m_valor.group(2) == "-" else "CREDITO"
                            current_entry["HISTORICO"] += " " + txt_orig.replace(m_valor.group(0), "").strip()

                        elif current_entry and len(txt_norm) > 2:
                            if not any(x in txt_norm for x in ["EXTRATO", "CONTA", "BANCO", "PAGINA"]):
                                current_entry["HISTORICO"] += " " + txt_orig.strip()

            if current_entry: registros.append(current_entry)

            # Filtragem final antes de salvar
            registros_limpos = []
            for reg in registros:
                hist_limpo = self.remover_acentos(re.sub(r'\s+', ' ', reg["HISTORICO"])).upper()
                if hist_limpo and reg["VALOR"] != 0 and "SALDO" not in hist_limpo:
                    reg["HISTORICO"] = hist_limpo
                    registros_limpos.append(reg)

            if registros_limpos:
                df = self.preparar_dataframe(registros_limpos)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0] + "_V1"
                    return self.salvar_arquivo(df, nome_base)

            log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
            return None

        except Exception as e:
            log_func(f"Erro ao processar BB V1 {arquivo}: {e}", "erro")
            return None


# ==========================================
# CLASSE 2: BB MODELO 2 (Novo Tabela)
# ==========================================
class BBProcessorV2(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "BB_V2"

    def _processar_transacao(self, buffer):
        """Processa o buffer de texto do BB V2"""
        if not buffer: return None
        texto_completo = buffer['texto']
        val_data = buffer['data']

        # Busca valores com "C" ou "D" no final (suporta vírgula ou ponto nos centavos)
        padrao_valor = r'(\d{1,3}(?:\.\d{3})*[.,]\d{2})\s*([DC])'
        matches = list(re.finditer(padrao_valor, texto_completo))
        if not matches: return None

        # Pega SEMPRE o primeiro valor (que é o valor do movimento). O saldo, se existir, vem depois.
        match_transacao = matches[0]
        val_str = match_transacao.group(1)
        tipo_letra = match_transacao.group(2)

        # Proteção: Alguns extratos do BB podem trazer "2.500.00" por erro de formatação do banco.
        # Se for ponto nos centavos, forçamos para vírgula antes de limpar.
        if len(val_str) >= 3 and val_str[-3] == '.':
            val_str = val_str[:-3] + ',' + val_str[-2:]

        val_final = self.limpar_valor(val_str)
        if tipo_letra == 'D':
            val_final = -abs(val_final)
            tipo = "DEBITO"
        else:
            val_final = abs(val_final)
            tipo = "CREDITO"

        # Limpeza pesada do histórico
        desc = texto_completo
        desc = re.sub(padrao_valor, '', desc)  # Remove todos os valores e saldos

        # Removemos códigos iniciais (Ex: "0000 14397 821 Pix...")
        desc = re.sub(r'^[\d\s]+', '', desc)

        # Removemos "lixo" de datas perdidas, horas e números de documento
        desc = re.sub(r'\d{2}/\d{2}\s+\d{2}:\d{2}', '', desc)
        desc = re.sub(r'\d{2}/\d{2}/\d{4}', '', desc)
        desc = re.sub(r'\b\d{2}/\d{2}\b', '', desc)
        desc = re.sub(r'\b\d{5,}\b', '', desc)
        desc = re.sub(r'\b\d+(?:\.\d+)+\b', '', desc)

        desc = desc.replace(" - ", " ").replace(" . ", " ")
        desc = re.sub(r'\s+', ' ', desc).strip()
        if desc.endswith("-"): desc = desc[:-1].strip()

        # Evita capturar linhas exclusivas de saldo final
        desc_upper = desc.upper()
        if "SALDO" in desc_upper and "ANTERIOR" in desc_upper: return None
        if desc_upper == "SALDO" or desc_upper == "S A L D O": return None

        if not desc: desc = "HISTORICO NAO IDENTIFICADO"

        return {
            "DATA": val_data,
            "HISTORICO": self.remover_acentos(desc).upper(),
            "VALOR": val_final,
            "TIPO": tipo
        }

    def processar(self, arquivo, log_func):
        log_func(f"Lendo BB V2 (Texto Contínuo): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            import pdfplumber
            texto_completo = ""

            # Substituímos a leitura de tabela pela leitura de texto bruto página a página
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    texto_pagina = page.extract_text()
                    if texto_pagina:
                        texto_completo += texto_pagina + "\n"

            if not texto_completo.strip():
                log_func(f"Aviso: Texto não detectado em {arquivo}.", "erro")
                return None

            linhas = texto_completo.split('\n')
            registros = []
            buffer_atual = None

            # Padrão: Para ser transação, a linha TEM que começar com uma Data (DD/MM/AAAA)
            padrao_data = r'^(\d{2}/\d{2}/\d{4})\s+(.*)'

            for linha in linhas:
                linha = linha.strip()
                if not linha: continue

                match_data = re.match(padrao_data, linha)

                if match_data:
                    # Encontrou o começo de uma transação! Se havia uma aberta, manda processar e salvar.
                    if buffer_atual:
                        res = self._processar_transacao(buffer_atual)
                        if res: registros.append(res)

                    # Inicia um novo pacote (buffer) para a nova transação
                    data_transacao = match_data.group(1)
                    texto_inicial = match_data.group(2)
                    buffer_atual = {'data': data_transacao, 'texto': texto_inicial}

                elif buffer_atual:
                    # A linha não começou com data, portanto é um pedaço do histórico da transação anterior
                    buffer_atual['texto'] += " " + linha

            # Quando acabar o documento, não esquecer de processar o último pacote que ficou aberto
            if buffer_atual:
                res = self._processar_transacao(buffer_atual)
                if res: registros.append(res)

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0] + "_V2"
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação válida encontrada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar BB V2 {arquivo}: {e}", "erro")
            return None