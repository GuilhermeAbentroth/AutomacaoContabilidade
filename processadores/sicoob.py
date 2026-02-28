import os
import re
import pdfplumber
from datetime import datetime
from base_processor import BaseProcessor


# ==========================================
# CLASSE 1: SICOOB CELULAR (Layout Colorido)
# ==========================================
class SicoobCelularProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "SICOOB_CELULAR"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo SICOOB (APP CELULAR): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)
        registros = []
        ano = str(datetime.now().year)
        buffer_h = []
        stop_p = False

        try:
            with pdfplumber.open(caminho_pdf) as pdf:
                # 1. Busca do Ano no Cabeçalho
                try:
                    txt_p1 = self.remover_acentos(pdf.pages[0].extract_text() or "")
                    m_ano = re.search(r"PERIODO:.*?/(\d{4})", txt_p1)
                    if m_ano: ano = m_ano.group(1)
                except Exception:
                    pass

                # 2. Leitura Geométrica e de Cores
                for page in pdf.pages:
                    if stop_p: break
                    words = page.extract_words(extra_attrs=['non_stroking_color'], x_tolerance=2, y_tolerance=2)
                    if not words: continue

                    linhas = []
                    curr_l = [words[0]]
                    for i in range(1, len(words)):
                        if abs(words[i]['top'] - curr_l[-1]['top']) < 3:
                            curr_l.append(words[i])
                        else:
                            linhas.append(curr_l)
                            curr_l = [words[i]]
                    if curr_l: linhas.append(curr_l)

                    # 3. Processamento das Linhas
                    for line in linhas:
                        txt_l = " ".join([w['text'] for w in line])
                        if "RESUMO" in txt_l.upper():
                            stop_p = True
                            break

                        m_d = re.search(r"(\d{2}/\d{2})", txt_l)
                        m_v = re.search(r"(\d{1,3}(?:\.\d{3})*,\d{2})", txt_l)

                        if m_v and m_d:
                            data_atu = m_d.group(1)
                            v_s = m_v.group(1)

                            # Extração da cor para saber se é Débito ou Crédito
                            cor = next((w.get('non_stroking_color') for w in line if v_s in w['text']), None)
                            r, b = (cor[0], cor[2]) if isinstance(cor, (list, tuple)) and len(cor) >= 3 else (0, 0)

                            tipo = "DEBITO" if (r > 0.5 and b < 0.5) or re.search(v_s + r"\s*D", txt_l) else "CREDITO"

                            h_l = re.sub(r"\s+[CD]$", "", txt_l.replace(data_atu, "").replace(v_s, "").strip())
                            hist_f = " ".join(buffer_h + [h_l]).strip()

                            if not any(x in hist_f.upper() for x in ["SALDO", "BLOQ"]):
                                val_limpo = self.limpar_valor(v_s)
                                registros.append({
                                    "DATA": f"{data_atu}/{ano}",
                                    "HISTORICO": self.remover_acentos(hist_f).upper(),
                                    "VALOR": -abs(val_limpo) if tipo == "DEBITO" else abs(val_limpo),
                                    "TIPO": tipo
                                })
                            buffer_h = []
                        else:
                            # Linhas sem valor vão para o buffer de histórico
                            if m_d: data_atu = m_d.group(1)
                            t_l = txt_l.replace(data_atu if m_d else "", "").strip()
                            if len(t_l) > 2 and not any(x in t_l.upper() for x in ["EXTRATO", "CONTA"]):
                                buffer_h.append(t_l)

            # 4. Finalização
            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0] + "_CELULAR"
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar Celular {arquivo}: {e}", "erro")
            return None


# ==========================================
# CLASSE 2: SICOOB DESKTOP (PDF Padrão)
# ==========================================
class SicoobDesktopProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "SICOOB_DESKTOP"

    def _processar_transacao(self, buffer, ano_padrao):
        """Processa o buffer de texto do Sicoob Desktop"""
        if not buffer: return None

        texto_completo = buffer['texto']
        dia_mes = buffer['data_raw']

        padrao_valor = r'(R\$\s*[\d\.]+,\d{2})\s*([DC])?'
        match_valor = re.search(padrao_valor, texto_completo)

        if not match_valor: return None

        val_str = match_valor.group(1).replace("R$", "").strip()
        tipo_letra = match_valor.group(2) if match_valor.group(2) else "C"

        val_final = self.limpar_valor(val_str)
        if tipo_letra == 'D':
            val_final = -abs(val_final)
            tipo = "DEBITO"
        else:
            val_final = abs(val_final)
            tipo = "CREDITO"

        desc = texto_completo.replace(match_valor.group(0), "")
        desc = re.sub(r'^\s*\d+\s+', '', desc)
        desc = re.sub(r'^\s*Pix\s+PIX', 'PIX', desc, flags=re.IGNORECASE)
        desc = desc.replace('\n', ' ').strip()
        desc = re.sub(r'\s+', ' ', desc)

        if "SALDO DO DIA" in desc.upper() or "SALDO ANTERIOR" in desc.upper():
            return None

        data_final = f"{dia_mes}/{ano_padrao}"

        return {
            "DATA": data_final,
            "HISTORICO": self.remover_acentos(desc).upper(),
            "VALOR": val_final,
            "TIPO": tipo
        }

    def processar(self, arquivo, log_func):
        log_func(f"Lendo SICOOB (PDF DESKTOP): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            ano_extrato = str(datetime.now().year)
            with pdfplumber.open(caminho_pdf) as pdf:
                if len(pdf.pages) > 0:
                    txt_p1 = pdf.pages[0].extract_text() or ""
                    m_ano = re.search(r'\d{2}/\d{2}/(\d{4})', txt_p1)
                    if m_ano:
                        ano_extrato = m_ano.group(1)

            linhas_texto = []
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    texto = page.extract_text()
                    if texto:
                        linhas_texto.extend(texto.split('\n'))

            registros = []
            buffer_atual = None

            for linha in linhas_texto:
                linha_limpa = linha.strip()
                if not linha_limpa: continue

                match_inicio = re.match(r'^(\d{2}/\d{2})\s+(.*)(R\$\s*[\d\.]+,\d{2}[DC]?)', linha_limpa)
                match_data_only = re.match(r'^(\d{2}/\d{2})\s+', linha_limpa)

                if match_inicio:
                    if buffer_atual:
                        res = self._processar_transacao(buffer_atual, ano_extrato)
                        if res: registros.append(res)
                    buffer_atual = {
                        'data_raw': match_inicio.group(1),
                        'texto': match_inicio.group(2) + " " + match_inicio.group(3)
                    }
                elif match_data_only:
                    if buffer_atual:
                        res = self._processar_transacao(buffer_atual, ano_extrato)
                        if res: registros.append(res)
                    buffer_atual = {
                        'data_raw': match_data_only.group(1),
                        'texto': linha_limpa[5:]
                    }
                else:
                    if buffer_atual:
                        buffer_atual['texto'] += " " + linha_limpa

            if buffer_atual:
                res = self._processar_transacao(buffer_atual, ano_extrato)
                if res: registros.append(res)

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0] + "_DESKTOP"
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação encontrada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar Desktop {arquivo}: {e}", "erro")
            return None