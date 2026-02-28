import os
import re
import pdfplumber
from base_processor import BaseProcessor

class IfoodProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_banco = "IFOOD"

    def processar(self, arquivo, log_func):
        """
        Lê e extrai os dados de um PDF de repasse do iFood.
        Retorna o nome do ficheiro Excel gerado ou None em caso de falha.
        """
        log_func(f"Lendo IFOOD: {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)

        linhas_texto = []
        try:
            # 1. Extração de Texto Corrido
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    texto = page.extract_text()
                    if texto:
                        # Divide por linhas e limpa espaços vazios
                        linhas_texto.extend([l.strip() for l in texto.split('\n') if l.strip()])

            if not linhas_texto:
                log_func(f"Aviso: PDF vazio ou imagem em {arquivo}", "erro")
                return None

            registros = []

            # 2. Processamento Linha a Linha
            for linha in linhas_texto:
                # Filtros iniciais de linhas inúteis
                if "Saldo disponível" in linha or "Período selecionado" in linha:
                    continue

                # Busca DATA (DD/MM/AAAA)
                match_data = re.search(r'(\d{2}/\d{2}/\d{4})', linha)
                if not match_data:
                    continue

                val_data = match_data.group(1)

                # Busca VALOR (ex: -R$ 10,00 ou R$ 10,00)
                match_valor = re.search(r'(-?\s*R\$\s*[\d\.,]+)', linha)
                if not match_valor:
                    continue

                val_raw = match_valor.group(1)
                eh_negativo = "-" in val_raw

                # Limpa o valor utilizando o método herdado da BaseProcessor
                val_clean_str = val_raw.replace("-", "").replace("R$", "").strip()
                val_float = self.limpar_valor(val_clean_str)

                # Se o valor for 0, ignora a transação
                if val_float == 0:
                    continue

                if eh_negativo:
                    valor_final = -abs(val_float)
                    tipo = "DEBITO"
                else:
                    valor_final = abs(val_float)
                    tipo = "CREDITO"

                # Limpa a Descrição (Subtração do texto original)
                desc = linha.replace(val_data, "").replace(val_raw, "")
                desc = desc.replace("Movimentação", "").replace("Descrição da movimentação", "")
                desc = re.sub(r'\s+', ' ', desc).strip()

                if desc.startswith("- ") or desc.startswith(". "):
                    desc = desc[2:]

                # Ignora a linha de "Saldo do dia"
                if "SALDO DO DIA" in desc.upper():
                    continue

                if not desc:
                    desc = "DESCRICAO NAO IDENTIFICADA"

                registros.append({
                    "DATA": val_data,
                    "HISTORICO": self.remover_acentos(desc).upper(),
                    "VALOR": valor_final,
                    "TIPO": tipo
                })

            # 3. Finalização e Gravação
            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0]
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação encontrada em {arquivo} (Layout mudou?)", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar {arquivo}: {e}", "erro")
            return None