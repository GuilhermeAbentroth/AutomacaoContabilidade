import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class ItauProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "ITAU"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo Itaú (Lógica de Estado Restrita): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            registros = []
            transacao_atual = None

            for page in doc:
                linhas = page.get_text("text").split('\n')

                for linha in linhas:
                    linha_str = linha.strip()
                    if not linha_str: continue
                    linha_up = linha_str.upper()

                    # =========================================================
                    # 1. GUILHOTINA DE CABEÇALHO E SALDOS (FILTRO RÍGIDO)
                    # =========================================================
                    if linha_up in ["ITAÚ", "ITAU", "DATA", "LANÇAMENTOS", "VALOR (R$)", "SALDO (R$)", "RAZÃO SOCIAL",
                                    "CNPJ/CPF"]: continue
                    if "EXTRATO" in linha_up or "LIMITE DA CONTA" in linha_up: continue
                    if "UTILIZADO" in linha_up or "DISPONÍVEL" in linha_up or "DISPONIVEL" in linha_up: continue
                    if "AGÊNCIA" in linha_up or "CONTA" in linha_up: continue
                    if "PERÍODO:" in linha_up or "PERIODO:" in linha_up: continue
                    if "SALDO ANTERIOR" in linha_up: continue
                    # Mata as linhas de saldo diário antes de entrarem no processamento
                    if "SALDO TOTAL DISPONÍVEL" in linha_up or "SALDO TOTAL DISPONIVEL" in linha_up: continue

                    # =========================================================
                    # 2. DETECÇÃO DE NOVA DATA (FECHA A ANTERIOR E ABRE NOVA)
                    # =========================================================
                    match_data = re.match(r'^(\d{2}/\d{2}/\d{4})(.*)', linha_str)

                    if match_data:
                        # Se já tínhamos uma transação, tentamos salvar antes de resetar
                        if transacao_atual:
                            valida = self._finalizar_e_validar(transacao_atual)
                            if valida: registros.append(valida)

                        data_encontrada = match_data.group(1)
                        resto = match_data.group(2).strip()

                        transacao_atual = {
                            "data": data_encontrada,
                            "historico": resto if resto else "",
                            "valor_str": None,
                            "tem_saldo_dia": False  # Marcador para evitar lixo
                        }
                        continue

                    # =========================================================
                    # 3. CAPTURA DE VALORES E HISTÓRICO ADICIONAL
                    # =========================================================
                    if transacao_atual:
                        # Procuramos o valor (padrão 1.234,56 ou -1.234,56)
                        match_valor = re.match(r'^-?[\d\.]*,\d{2}$', linha_str)

                        if match_valor:
                            # No Itaú, o primeiro valor após a data é a transação. O segundo é o saldo.
                            if not transacao_atual["valor_str"]:
                                transacao_atual["valor_str"] = linha_str
                            else:
                                # Se já temos valor, o que vier agora é o saldo do dia, ignoramos.
                                pass
                        else:
                            # Se não é valor nem data, é continuação do nome/descrição
                            # Limpa CNPJ/CPF no caminho
                            l = re.sub(r'\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}', '', linha_str)
                            l = re.sub(r'\d{3}\.\d{3}\.\d{3}-\d{2}', '', l).strip()

                            if l:
                                separator = " " if transacao_atual["historico"] else ""
                                transacao_atual["historico"] += separator + l

            # Salva a última do PDF
            if transacao_atual:
                valida = self._finalizar_e_validar(transacao_atual)
                if valida: registros.append(valida)

            # =========================================================
            # 4. REGRA FINAL: REMOVER ÚLTIMO LANÇAMENTO (SALDO DO PERÍODO)
            # =========================================================
            if registros:
                registros.pop()

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    return self.salvar_arquivo(df, os.path.splitext(arquivo)[0])

            log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
            return None

        except Exception as e:
            log_func(f"Erro Crítico Itaú {arquivo}: {e}", "erro")
            return None

    def _finalizar_e_validar(self, t):
        """Valida se a transação é real ou apenas um saldo perdido."""
        if not t["valor_str"]: return None

        hist = t["historico"].upper().strip()

        # Se o histórico for vazio ou contiver apenas palavras de saldo, descartamos
        if not hist or "SALDO TOTAL" in hist or "SALDO ANTERIOR" in hist:
            return None

        # Se o histórico for muito curto (ex: apenas um caractere órfão), descartamos
        if len(hist) < 3:
            return None

        val_clean = self.limpar_valor(t["valor_str"].replace("-", "").replace("+", ""))
        if val_clean == 0: return None

        eh_negativo = "-" in t["valor_str"]
        historico_final = self.remover_acentos(hist)

        return {
            "DATA": t["data"],
            "HISTORICO": historico_final,
            "VALOR": -abs(val_clean) if eh_negativo else abs(val_clean),
            "TIPO": "DEBITO" if eh_negativo else "CREDITO"
        }