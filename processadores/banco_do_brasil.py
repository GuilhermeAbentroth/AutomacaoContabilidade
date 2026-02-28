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

    def _extrair_tabelas(self, caminho_pdf):
        """Método interno para extrair as tabelas do PDF"""
        dados_tabela = []
        with pdfplumber.open(caminho_pdf) as pdf:
            for page in pdf.pages:
                tabela = page.extract_table({
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text"
                })
                if tabela:
                    for linha in tabela:
                        if linha and any(linha):
                            dados_tabela.append(linha)
        return dados_tabela

    def _processar_transacao(self, buffer):
        """Processa o buffer de texto do BB V2"""
        if not buffer: return None
        texto_completo = buffer['texto']
        val_data = buffer['data']

        # Busca valores com "C" ou "D" no final
        padrao_valor = r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*([DC])'
        matches = list(re.finditer(padrao_valor, texto_completo))
        if not matches: return None

        match_transacao = matches[0]
        val_str = match_transacao.group(1)
        tipo_letra = match_transacao.group(2)

        val_final = self.limpar_valor(val_str)
        if tipo_letra == 'D':
            val_final = -abs(val_final)
            tipo = "DEBITO"
        else:
            val_final = abs(val_final)
            tipo = "CREDITO"

        # Limpeza pesada do histórico
        desc = texto_completo
        desc = re.sub(padrao_valor, '', desc)
        desc = re.sub(r'^[\d\s]+', '', desc)  # Remove códigos iniciais
        desc = re.sub(r'\d{2}/\d{2}\s+\d{2}:\d{2}', '', desc)  # Remove datas/horas perdidas
        desc = re.sub(r'\d{2}/\d{2}', '', desc)
        desc = re.sub(r'\b\d{5,}\b', '', desc)  # Remove números grandes de docs
        desc = re.sub(r'\b\d+(?:\.\d+)+\b', '', desc)  # Remove números formatados aleatórios

        desc = desc.replace(" - ", " ").replace(" . ", " ")
        desc = re.sub(r'\s+', ' ', desc).strip()
        if desc.endswith("-"): desc = desc[:-1].strip()

        if "SALDO" in desc.upper() and "ANTERIOR" in desc.upper(): return None
        if not desc: desc = "HISTORICO NAO IDENTIFICADO"

        return {
            "DATA": val_data,
            "HISTORICO": self.remover_acentos(desc).upper(),
            "VALOR": val_final,
            "TIPO": tipo
        }

    def processar(self, arquivo, log_func):
        log_func(f"Lendo BB V2 (Tabelado): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            dados_tabela = self._extrair_tabelas(caminho_pdf)

            if not dados_tabela:
                log_func(f"Aviso: Tabela não detectada em {arquivo}.", "erro")
                return None

            registros = []
            buffer_atual = None

            for linha in dados_tabela:
                cols = [str(c).replace('\n', ' ').strip() if c else "" for c in linha]
                if not any(cols): continue

                col_0 = cols[0]

                if re.match(r'\d{2}/\d{2}/\d{4}', col_0):
                    if buffer_atual:
                        res = self._processar_transacao(buffer_atual)
                        if res: registros.append(res)

                    texto_inicial = " ".join(cols[1:])
                    buffer_atual = {'data': col_0, 'texto': texto_inicial}

                elif buffer_atual:
                    texto_extra = " ".join(cols)
                    buffer_atual['texto'] += " " + texto_extra

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