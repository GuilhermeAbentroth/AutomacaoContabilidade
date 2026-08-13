import os
import re
import fitz  # PyMuPDF
from base_processor import BaseProcessor


class BradescoProcessor(BaseProcessor):
    """
    Extratos Bradesco Net Empresa: cada célula da tabela vira uma linha
    isolada no texto extraído (data / histórico / doc / valor / saldo
    sempre em linhas separadas), por isso usamos uma máquina de estados
    em vez de parsear "uma linha = uma transação".
    """

    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "BRADESCO"

    def processar(self, arquivo, log_func):
        log_func(f"Lendo BRADESCO: {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        try:
            doc = fitz.open(caminho_pdf)
            registros = []

            data_atual = None
            buffer_desc = []
            valor_pendente = None
            aguardando_saldo_anterior = False
            encerrou = False

            for page in doc:
                if encerrou: break
                linhas = page.get_text("text").split('\n')

                for linha in linhas:
                    linha_str = linha.strip()
                    if not linha_str: continue
                    linha_up = linha_str.upper()

                    # Encerra a leitura ao chegar na linha de total do extrato principal
                    if linha_up == "TOTAL":
                        encerrou = True
                        break

                    # Rodapé/cabeçalho repetido em cada página (não é lançamento)
                    if re.match(r'^FOLHA\s+\d+/\d+$', linha_up): continue
                    if "EXTRATO MENSAL" in linha_up or "POR PER" in linha_up and "ODO" in linha_up: continue
                    if "CNPJ" in linha_up: continue
                    if "NOME DO USU" in linha_up: continue
                    if "DATA DA OPERA" in linha_up: continue

                    # Data isolada na própria linha -> abre um novo dia
                    if re.fullmatch(r'\d{2}/\d{2}/\d{4}', linha_str):
                        data_atual = linha_str
                        buffer_desc = []
                        valor_pendente = None
                        aguardando_saldo_anterior = False
                        continue

                    if data_atual is None:
                        continue  # ainda no cabeçalho do extrato

                    if linha_up == "SALDO ANTERIOR":
                        aguardando_saldo_anterior = True
                        continue

                    match_valor = re.fullmatch(r'-?[\d\.]+,\d{2}', linha_str)
                    if match_valor:
                        if aguardando_saldo_anterior:
                            # Apenas o saldo de abertura do dia, não é lançamento
                            aguardando_saldo_anterior = False
                            continue

                        if valor_pendente is None:
                            valor_pendente = linha_str
                        else:
                            # Segundo valor numérico = saldo -> fecha a transação
                            hist_puro = " ".join(buffer_desc).strip()
                            hist_puro = re.sub(r'\s+', ' ', hist_puro)
                            if not hist_puro: hist_puro = "HISTORICO NAO IDENTIFICADO"

                            val_clean = self.limpar_valor(valor_pendente.replace("-", ""))
                            if val_clean != 0:
                                eh_negativo = valor_pendente.startswith("-")
                                registros.append({
                                    "DATA": data_atual,
                                    "HISTORICO": self.remover_acentos(hist_puro).upper(),
                                    "VALOR": -abs(val_clean) if eh_negativo else abs(val_clean),
                                    "TIPO": "DEBITO" if eh_negativo else "CREDITO"
                                })

                            buffer_desc = []
                            valor_pendente = None
                        continue

                    # Linhas com apenas números (doc/agência/etc.) são descartadas
                    if re.fullmatch(r'\d+', linha_str):
                        continue

                    buffer_desc.append(linha_str)

            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    return self.salvar_arquivo(df, os.path.splitext(arquivo)[0])

            log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
            return None

        except Exception as e:
            log_func(f"Erro ao processar Bradesco {arquivo}: {e}", "erro")
            return None
