import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class InterProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "INTER"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo INTER (Guilhotina de Rodapé): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            linhas = []

            # =========================================================
            # 1. AGRUPAMENTO COM A SUA IDEIA DA GUILHOTINA
            # =========================================================
            for page in doc:
                words = page.get_text("words")
                if not words: continue

                # Descobre dinamicamente a altura do Cabeçalho para o cortar
                y_corte_top = 0
                for w in words:
                    texto_w = w[4].upper()
                    if "CPF" in texto_w or "CNPJ" in texto_w or "PERÍODO" in texto_w or "PERIODO" in texto_w:
                        y_corte_top = max(y_corte_top, w[1] + 15)

                words_uteis = [w for w in words if w[1] >= y_corte_top]
                if not words_uteis: continue

                words_uteis.sort(key=lambda w: (w[1], w[0]))

                linha_atual = []
                y_ref = None
                linhas_da_pagina = []

                for w in words_uteis:
                    if y_ref is None:
                        linha_atual.append(w)
                        y_ref = w[1]
                    elif abs(w[1] - y_ref) <= 4:
                        linha_atual.append(w)
                    else:
                        linha_atual.sort(key=lambda x: x[0])
                        linhas_da_pagina.append(" ".join([x[4] for x in linha_atual]))
                        linha_atual = [w]
                        y_ref = w[1]

                if linha_atual:
                    linha_atual.sort(key=lambda x: x[0])
                    linhas_da_pagina.append(" ".join([x[4] for x in linha_atual]))

                # =========================================================
                # O SEU "KILL SWITCH" DO RODAPÉ (Fale com a gente, etc.)
                # =========================================================
                for linha in linhas_da_pagina:
                    linha_up = linha.upper()

                    rodape_triggers = [
                        "FALE COM A", "FALE COM A GENTE", "OUVIDORIA", "CENTRAL DE RELACIONAMENTO",
                        "CAPITAIS E REGIÕES METROPOLITANAS", "CAPITAIS E REGIOES", "DEMAIS LOCALIDADES",
                        "PÁGINA", "PAGINA", "BANCO INTER"
                    ]

                    if any(x in linha_up for x in rodape_triggers):
                        break  # CORTA AQUI! Abandona o resto desta página imediatamente!

                    linhas.append(linha)

            if not linhas:
                log_func(f"Aviso: Nenhuma linha útil encontrada em {arquivo}", "erro")
                return None

            registros = []
            data_atual = None
            buffer_desc = ""

            meses = {
                "JANEIRO": "01", "FEVEREIRO": "02", "MARCO": "03", "MARÇO": "03", "ABRIL": "04",
                "MAIO": "05", "JUNHO": "06", "JULHO": "07", "AGOSTO": "08",
                "SETEMBRO": "09", "OUTUBRO": "10", "NOVEMBRO": "11", "DEZEMBRO": "12"
            }

            # Lixo Sistêmico
            lixo_parcial = ["SALDO DISPONIVEL", "SALDO DISPONÍVEL", "SALDO BLOQUEADO"]
            lixo_exato = ["INTER", "VALOR", "SALDO"]

            # =========================================================
            # 2. MÁQUINA DE ESTADOS CONTÍNUA DO INTER
            # =========================================================
            for linha in linhas:
                linha_str = linha.strip()
                if not linha_str: continue

                linha_str = re.sub(r'(?i)VALOR\s+SALDO\s+POR\s+TRANSA[CÇ][AÃ]O', '', linha_str).strip()
                linha_str = re.sub(r'(?i)SALDO\s+POR\s+TRANSA[CÇ][AÃ]O', '', linha_str).strip()
                linha_up = linha_str.upper()

                # PASSO 1: DATA
                match_data = re.search(r'\b(\d{1,2})\s+DE\s+([A-ZÇ]+)\s+DE\s+(\d{4})\b', linha_up)
                if match_data:
                    dia = match_data.group(1).zfill(2)
                    mes_nome = match_data.group(2)
                    ano = match_data.group(3)

                    if mes_nome in meses:
                        data_atual = f"{dia}/{meses[mes_nome]}/{ano}"

                    linha_str = linha_str[:match_data.start()] + linha_str[match_data.end():]
                    linha_str = re.sub(r'(?i)SALDO DO DIA:?\s*R\$\s*[\d\.,]+', '', linha_str).strip()
                    linha_up = linha_str.upper()

                if not linha_str:
                    continue

                # PASSO 2: FILTROS DE LIXO SEGUROS
                if linha_up in lixo_exato:
                    continue
                if any(x in linha_up for x in lixo_parcial):
                    continue

                if not data_atual:
                    continue

                # PASSO 3: CAPTURA DE VALORES E GRAVAÇÃO
                valores = re.findall(r'(-?\s*R\$\s*[\d\.,]+)', linha_str, re.IGNORECASE)

                if valores:
                    val_str_raw = valores[0]

                    texto_resto = linha_str
                    for v in valores:
                        texto_resto = texto_resto.replace(v, "")

                    if texto_resto.strip():
                        buffer_desc += " " + texto_resto.strip()

                    eh_negativo = "-" in val_str_raw
                    val_clean = self.limpar_valor(val_str_raw.replace("R$", "").replace("-", "").strip())

                    if val_clean > 0:
                        desc_final = buffer_desc.strip()
                        # Limpa aspas
                        desc_final = desc_final.replace('""', '').replace('"', '').replace("''", "").strip()

                        if not desc_final:
                            desc_final = "HISTORICO NAO IDENTIFICADO"

                        registros.append({
                            "DATA": data_atual,
                            "HISTORICO": self.remover_acentos(desc_final).upper(),
                            "VALOR": -abs(val_clean) if eh_negativo else abs(val_clean),
                            "TIPO": "DEBITO" if eh_negativo else "CREDITO"
                        })

                    buffer_desc = ""

                else:
                    buffer_desc += " " + linha_str

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0]
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar INTER {arquivo}: {e}", "erro")
            return None