import os
import re
import pdfplumber
from base_processor import BaseProcessor


class AilosProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_banco = "AILOS"

    def processar(self, arquivo, log_func):
        """
        Lê e extrai os dados de um único PDF do banco Ailos.
        Retorna o nome do ficheiro Excel gerado ou None em caso de falha.
        """
        log_func(f"Lendo AILOS: {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)
        dados_brutos = []

        try:
            # 1. Extração do PDF
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    tabela = page.extract_table({
                        "vertical_strategy": "text",
                        "horizontal_strategy": "text"
                    })
                    if tabela:
                        for linha in tabela:
                            if linha and any(linha):
                                dados_brutos.append(linha)

            if not dados_brutos:
                log_func(f"Aviso: Nenhuma tabela encontrada em {arquivo}", "erro")
                return None

            registros = []

            # 2. Varredura e Tratamento das Linhas
            for linha in dados_brutos:
                cols = [str(x).strip() if x else "" for x in linha]
                if len(cols) < 5: continue

                val_data = cols[0]
                if not re.search(r'\d{2}/\d{2}/\d{4}', val_data):
                    continue

                val_deb = cols[-2]
                val_cred = cols[-3]

                itens_descricao = cols[1:-4]
                val_desc = " ".join(itens_descricao).strip()
                if not val_desc and len(cols) >= 5:
                    val_desc = " ".join(cols[1:-3]).strip()

                valor_final = 0.0
                tipo = ""

                # Utiliza o self.limpar_valor (herdado da BaseProcessor)
                if val_deb and re.search(r'[\d,]', val_deb):
                    v = self.limpar_valor(val_deb)
                    if v != 0:
                        valor_final = -abs(v)
                        tipo = "DEBITO"
                elif val_cred and re.search(r'[\d,]', val_cred):
                    v = self.limpar_valor(val_cred)
                    if v != 0:
                        valor_final = abs(v)
                        tipo = "CREDITO"

                if valor_final != 0:
                    registros.append({
                        "DATA": val_data,
                        # Utiliza o self.remover_acentos (herdado)
                        "HISTORICO": self.remover_acentos(val_desc).upper(),
                        "VALOR": valor_final,
                        "TIPO": tipo
                    })

            # 3. Finalização e Gravação usando as ferramentas do Pai
            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0]
                    ficheiro_salvo = self.salvar_arquivo(df, nome_base)
                    # Não colocamos log de sucesso total aqui, deixamos para o Maestro
                    return ficheiro_salvo
            else:
                log_func(f"Aviso: Layout não reconhecido ou sem transações em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar {arquivo}: {e}", "erro")
            return None