import os
import re
import fitz  # PyMuPDF (A nossa nova "arma" para ler PDFs perfeitamente)
import pdfplumber
from base_processor import BaseProcessor


# ==========================================
# CLASSE 1: SANTANDER V1 (Mantida Intacta)
# ==========================================
class SantanderProcessorV1(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "SANTANDER_V1"
        self.mapa_meses = {
            'JANEIRO': '01', 'FEVEREIRO': '02', 'MARCO': '03',
            'ABRIL': '04', 'MAIO': '05', 'JUNHO': '06', 'JULHO': '07',
            'AGOSTO': '08', 'SETEMBRO': '09', 'OUTUBRO': '10', 'NOVEMBRO': '11', 'DEZEMBRO': '12'
        }

    def processar(self, arquivo, log_func):
        log_func(f"Lendo SANTANDER V1: {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)
        registros = []
        data_atual_contexto = None

        try:
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    texto = page.extract_text()
                    if not texto: continue
                    linhas = texto.split('\n')

                    for linha in linhas:
                        linha_limpa = linha.strip()
                        match_cabecalho = re.search(r',\s*(\d{1,2})\s+de\s+([a-zA-ZçÇ]+)\s+de\s+(\d{4})', linha_limpa,
                                                    re.IGNORECASE)

                        if match_cabecalho:
                            dia = match_cabecalho.group(1).zfill(2)
                            mes_nome = self.remover_acentos(match_cabecalho.group(2))
                            ano = match_cabecalho.group(3)
                            mes_num = self.mapa_meses.get(mes_nome, '01')
                            data_atual_contexto = f"{dia}/{mes_num}/{ano}"
                            continue

                        if data_atual_contexto:
                            match_valor = re.search(r'(R\$\s*[\d\.,]+)', linha_limpa)
                            if match_valor:
                                val_str = match_valor.group(1)
                                val_clean = self.limpar_valor(val_str)
                                linha_upper = linha_limpa.upper()

                                if "DEBITO" in linha_upper:
                                    valor_final, tipo = -abs(val_clean), "DEBITO"
                                elif "CREDITO" in linha_upper:
                                    valor_final, tipo = abs(val_clean), "CREDITO"
                                else:
                                    continue

                                desc = linha_upper.split("CREDITO")[0].split("DEBITO")[0]
                                desc = desc.replace(val_str.upper(), "").strip()
                                if not desc: desc = "HISTORICO NAO IDENTIFICADO"

                                registros.append({
                                    "DATA": data_atual_contexto,
                                    "HISTORICO": self.remover_acentos(desc).upper(),
                                    "VALOR": valor_final,
                                    "TIPO": tipo
                                })

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    return self.salvar_arquivo(df, os.path.splitext(arquivo)[0] + "_V1")
            else:
                log_func(f"Aviso: Nenhuma transação V1 encontrada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar {arquivo}: {e}", "erro")
            return None


# ==========================================
# CLASSE 2: SANTANDER V2 (Empresas - Y-Bounding Espacial)
# ==========================================
class SantanderProcessorV2(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "SANTANDER_V2"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo Santander V2 (Regra Stone c/ Exclusão Final): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        import fitz  # PyMuPDF

        try:
            doc = fitz.open(caminho_pdf)
            texto_global = ""

            for page in doc:
                texto = page.get_text("text")
                linhas = texto.split('\n')

                for linha in linhas:
                    linha_str = linha.strip()
                    if not linha_str: continue
                    linha_up = linha_str.upper()

                    # Ignora lixo óbvio do cabeçalho
                    if "SANTANDER" in linha_up and "EMPRESA" in linha_up: continue
                    if "AGÊNCIA:" in linha_up or "AGENCIA:" in linha_up or "CONTA:" in linha_up: continue
                    if "PERÍODOS:" in linha_up or "PERIODOS:" in linha_up or "DATA/HORA:" in linha_up: continue
                    if linha_up in ["DATA", "HISTÓRICO", "DOCUMENTO", "VALOR (R$)", "SALDO (R$)"]: continue
                    if re.match(r'^\d+/\d+$', linha_str): continue  # Elimina paginação "1/3"

                    texto_global += " " + linha_str

            # Limpa espaços duplos
            texto_global = re.sub(r'\s+', ' ', texto_global).strip()

            # =========================================================
            # A FACADA NAS DATAS (Divide perfeitamente as transações)
            # =========================================================
            chunks = re.split(r'(?=\b\d{2}/\d{2}/\d{4}\b)', texto_global)

            registros = []
            for chunk in chunks:
                chunk = chunk.strip()
                if not re.match(r'^\d{2}/\d{2}/\d{4}', chunk): continue

                data_str = chunk[:10]
                resto = chunk[10:].strip()

                matches_valor = list(re.finditer(r'-?[\d\.]*,\d{2}', resto))
                if not matches_valor: continue

                # O primeiro valor é SEMPRE a transação financeira
                val_str_raw = matches_valor[0].group(0)

                # Remove TODOS os valores e saldos da string do histórico
                for m in matches_valor:
                    resto = resto.replace(m.group(0), "")

                hist_puro = resto.upper()
                hist_puro = re.sub(r'\b\d{5,}\b', '', hist_puro)  # Limpa IDs de documentos

                # Guilhotina Local: Limpa o texto residual do rodapé
                marcadores_fim = [
                    "ENTENDA A COMPOS",
                    "SALDO DE CONTAMAX",
                    "A- SALDO DE CONTA",
                    "B-SALDO BLOQUEADO",
                    "C-PROVISAO",
                    "RESUMO DOS LIMITES",
                    "POSICAO EM:",
                    "POSIÇÃO EM:",
                    "SALDO DISPONIVEL",
                    "SALDO DISPONÍVEL"
                ]

                for marcador in marcadores_fim:
                    if marcador in hist_puro:
                        hist_puro = hist_puro.split(marcador)[0]

                hist_puro = re.sub(r'\s+', ' ', hist_puro).strip()

                # Ignora a linha de Saldo Anterior do topo
                if "SALDO ANTERIOR" in hist_puro and len(hist_puro) < 25:
                    continue

                historico_final = self.remover_acentos(hist_puro)
                if not historico_final: historico_final = "LANCAMENTO SANTANDER"

                val_clean = self.limpar_valor(val_str_raw.replace("-", "").replace("+", ""))
                if val_clean == 0: continue

                eh_negativo = "-" in val_str_raw
                tipo = "DEBITO" if eh_negativo else "CREDITO"
                valor_final = -abs(val_clean) if eh_negativo else abs(val_clean)

                registros.append({
                    "DATA": data_str,
                    "HISTORICO": historico_final,
                    "VALOR": valor_final,
                    "TIPO": tipo
                })

            # =========================================================
            # EXCLUSÃO DO ÚLTIMO LANÇAMENTO (SALDO FINAL)
            # =========================================================
            # Aqui aplicamos a sua regra: apagamos a última linha coletada!
            if registros:
                registros.pop()

            # =========================================================
            # FINALIZAÇÃO
            # =========================================================
            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0] + "_V2"
                    return self.salvar_arquivo(df, nome_base)

            log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
            return None

        except Exception as e:
            log_func(f"Erro Santander V2 {arquivo}: {e}", "erro")
            return None