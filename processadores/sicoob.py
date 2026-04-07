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
        log_func(f"Lendo SICOOB (APP CELULAR - Máquina de Estados): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)
        registros = []
        ano = str(datetime.now().year)

        try:
            with pdfplumber.open(caminho_pdf) as pdf:
                # 1. Busca do Ano no Cabeçalho
                try:
                    txt_p1 = self.remover_acentos(pdf.pages[0].extract_text() or "")
                    m_ano = re.search(r"PERIODO:.*?/(\d{4})", txt_p1)
                    if m_ano: ano = m_ano.group(1)
                except Exception:
                    pass

                stop_p = False
                transacao_atual = None

                # 2. Leitura com Máquina de Estados Lineares
                for page in pdf.pages:
                    if stop_p: break
                    words = page.extract_words(extra_attrs=['non_stroking_color'])
                    if not words: continue

                    # Ordena rigidamente de cima para baixo, esquerda para a direita
                    words.sort(key=lambda w: (w['top'], w['x0']))
                    linhas = []
                    linha_atual = []
                    y_ref = None

                    # Reconstrói as linhas perfeitamente
                    for w in words:
                        if y_ref is None:
                            linha_atual.append(w)
                            y_ref = w['top']
                        elif abs(w['top'] - y_ref) <= 4:
                            linha_atual.append(w)
                        else:
                            linha_atual.sort(key=lambda x: x['x0'])
                            linhas.append(" ".join([x['text'] for x in linha_atual]))
                            linha_atual = [w]
                            y_ref = w['top']

                    if linha_atual:
                        linha_atual.sort(key=lambda x: x['x0'])
                        linhas.append(" ".join([x['text'] for x in linha_atual]))

                    # Processamento Linha a Linha (Onde a Mágica Acontece)
                    for txt_l in linhas:
                        txt_l = txt_l.strip()
                        if not txt_l: continue

                        txt_upper = txt_l.upper()

                        # Trava de Segurança
                        if "RESUMO" in txt_upper:
                            stop_p = True
                            break

                        # Pula todo o lixo do Sicoob Celular
                        skip_phrases = [
                            "SICOOB", "SISTEMA DE COOPERATIVAS", "SISBR",
                            "DATA HISTÓRICO VALOR", "SALDO ANTERIOR",
                            "SALDO BLOQ", "SALDO DO DIA", "SALDOS", "OUVIDORIA"
                        ]
                        if any(x in txt_upper for x in skip_phrases) or txt_upper == "SALDO":
                            continue

                        # A. Encontrou uma Data? -> Inicia Nova Transação!
                        m_d = re.match(r'^(\d{2}/\d{2})(?:/\d{2,4})?', txt_l)
                        if m_d:
                            # Salva a transação antiga (se existir) antes de abrir a nova
                            if transacao_atual and transacao_atual["VALOR"] is not None:
                                hist_limpo = self.remover_acentos(transacao_atual["HISTORICO"]).upper()
                                hist_limpo = re.sub(r'\s+', ' ', hist_limpo).strip(" -|.")
                                transacao_atual["HISTORICO"] = hist_limpo
                                registros.append(transacao_atual)

                            data_atu = m_d.group(1)
                            transacao_atual = {
                                "DATA": f"{data_atu}/{ano}",
                                "HISTORICO": "",
                                "VALOR": None,
                                "TIPO": None
                            }
                            # Retira a data da string para não sujar o histórico
                            txt_l = txt_l.replace(m_d.group(0), "", 1).strip()

                        # B. Procura pelo Valor da Transação na Linha
                        if transacao_atual:
                            matches_v = list(re.finditer(r'(\d{1,3}(?:\.\d{3})*,\d{2})\s*([DCdc])?', txt_l))

                            # Se encontrar valor e a transação atual ainda não tiver um
                            if matches_v and transacao_atual["VALOR"] is None:
                                match_v = matches_v[-1]  # Pega o último valor da linha
                                v_s = match_v.group(1)
                                sufixo = match_v.group(2)

                                tipo = "CREDITO"
                                if sufixo and sufixo.upper() == 'D':
                                    tipo = "DEBITO"
                                elif sufixo and sufixo.upper() == 'C':
                                    tipo = "CREDITO"
                                else:
                                    # Fallback Inteligente: Avalia a Cor (Débito é Vermelho no Sicoob App)
                                    cor = next((w.get('non_stroking_color') for w in words if v_s in w['text']), None)
                                    r, b = (cor[0], cor[2]) if isinstance(cor, (list, tuple)) and len(cor) >= 3 else (0,
                                                                                                                      0)
                                    if r > 0.5 and b < 0.5:
                                        tipo = "DEBITO"

                                val_limpo = self.limpar_valor(v_s)
                                transacao_atual["VALOR"] = -abs(val_limpo) if tipo == "DEBITO" else abs(val_limpo)
                                transacao_atual["TIPO"] = tipo

                                # Remove o valor da string para não sujar o histórico
                                txt_l = txt_l.replace(match_v.group(0), "", 1).strip()

                        # C. O que sobrar na linha é adicionado ao Histórico da Transação
                        if transacao_atual and txt_l:
                            # Ignora se sobrar apenas um "D" ou "C" isolado, ou um valor solto de saldo
                            if txt_l.upper() not in ["D", "C"] and not re.match(r'^\d{1,3}(?:\.\d{3})*,\d{2}[DCdc]?$',
                                                                                txt_l.strip()):
                                transacao_atual["HISTORICO"] += " " + txt_l

                # 3. Garante que a última transação da página seja guardada
                if transacao_atual and transacao_atual["VALOR"] is not None:
                    hist_limpo = self.remover_acentos(transacao_atual["HISTORICO"]).upper()
                    hist_limpo = re.sub(r'\s+', ' ', hist_limpo).strip(" -|.")
                    transacao_atual["HISTORICO"] = hist_limpo
                    registros.append(transacao_atual)

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