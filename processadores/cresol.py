import os
import re
import pdfplumber
from base_processor import BaseProcessor


class CresolProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "CRESOL"

    def processar(self, arquivo, log_func):
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            texto_global = ""

            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    words = page.extract_words(x_tolerance=3, y_tolerance=3)
                    if not words: continue

                    words.sort(key=lambda w: w['top'])
                    linhas_da_pagina = []
                    if words:
                        linha_atual = [words[0]]
                        for w in words[1:]:
                            if abs(w['top'] - linha_atual[0]['top']) <= 5:
                                linha_atual.append(w)
                            else:
                                linhas_da_pagina.append(linha_atual)
                                linha_atual = [w]
                        if linha_atual:
                            linhas_da_pagina.append(linha_atual)

                    for linha in linhas_da_pagina:
                        linha.sort(key=lambda w: w['x0'])
                        texto_linha = " ".join([w['text'] for w in linha]).strip()

                        if not texto_linha: continue

                        tl_upper = texto_linha.upper()
                        if "SALDO DO DIA" in tl_upper or "SALDO ANTERIOR" in tl_upper: continue
                        if "SALDO EM CONTA" in tl_upper or "SALDO DISPON" in tl_upper: continue
                        if "CONSULTA POSI" in tl_upper: continue
                        if "PERIODO DE" in tl_upper or "PÁGINA" in tl_upper or "PAGINA" in tl_upper: continue
                        if "LIMITE DE CR" in tl_upper: continue
                        if "LANÇAMENTOS" == tl_upper or "LANCAMENTOS" == tl_upper: continue
                        if re.match(r'^\d{2} DE [A-Z]+ DE \d{4}', tl_upper): continue

                        texto_global += " " + texto_linha

            texto_global = re.sub(r'\s+', ' ', texto_global).strip()

            chunks = re.split(r'(?=\b\d{2}/\d{2}/\d{4}\b)', texto_global)

            registros = []
            for chunk in chunks:
                chunk = chunk.strip()
                if not re.match(r'^\d{2}/\d{2}/\d{4}', chunk): continue

                matches_valor = list(re.finditer(r'([+-]?\s*R\$\s*[\d\.,]+)', chunk))
                if not matches_valor: continue

                transacao = matches_valor[-1]
                val_str_raw = transacao.group(1).replace(" ", "")

                val_clean = self.limpar_valor(val_str_raw.replace("+", "").replace("-", "").replace("R$", ""))
                if val_clean == 0: continue

                eh_negativo = "-" in val_str_raw
                eh_positivo = "+" in val_str_raw

                hist = chunk[10:]
                for m in matches_valor:
                    hist = hist.replace(m.group(0), "")

                hist = re.sub(r'\b\d{10,}\b', '', hist)
                hist = re.sub(r'^[-\s]+', '', hist)
                hist = re.sub(r'\s+', ' ', hist).strip()
                hist_upper = hist.upper()

                if "BLOQUEIO" in hist_upper and "DESBLOQUEIO" not in hist_upper:
                    eh_negativo = True
                elif "DESBLOQUEIO" in hist_upper:
                    eh_negativo = False
                elif not eh_negativo and not eh_positivo:
                    palavras_debito = ["DEBITO", "DÉBITO", "TARIFA", "CUSTAS", "PAGAMENTO", "SAQUE", "CHEQUE",
                                       "ENCARGO", "CONSORCIO", "MENSALIDADE", "IMPOSTO", "IOF"]
                    eh_negativo = any(p in hist_upper for p in palavras_debito)

                tipo = "DEBITO" if eh_negativo else "CREDITO"
                valor_final = -abs(val_clean) if eh_negativo else abs(val_clean)

                if not hist: hist = "HISTORICO NAO IDENTIFICADO"

                registros.append({
                    "DATA": chunk[:10],
                    "HISTORICO": self.remover_acentos(hist).upper(),
                    "VALOR": valor_final,
                    "TIPO": tipo
                })

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    return self.salvar_arquivo(df, os.path.splitext(arquivo)[0])

            log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
            return None

        except Exception as e:
            log_func(f"Erro CRESOL {arquivo}: {e}", "erro")
            return None