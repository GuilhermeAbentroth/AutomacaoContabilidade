import os
import re
import pdfplumber
from base_processor import BaseProcessor

# ==========================================
# CLASSE 1: SANTANDER V1 (Contexto de Data)
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
                        match_cabecalho = re.search(r',\s*(\d{1,2})\s+de\s+([a-zA-ZçÇ]+)\s+de\s+(\d{4})', linha_limpa, re.IGNORECASE)

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
# CLASSE 2: SANTANDER V2 (Empresas / Tabela)
# ==========================================
class SantanderProcessorV2(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_modelo = "SANTANDER_V2"

    def processar(self, arquivo, log_func):
        """
        Extrai dados do Extrato Santander Empresas.
        Lê linhas no formato: DD/MM/AAAA Histórico NumDoc Valor [Saldo]
        """
        log_func(f"Lendo SANTANDER V2 (Empresas): {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)
        registros = []

        try:
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    texto = page.extract_text()
                    if not texto: continue

                    linhas = texto.split('\n')
                    for linha in linhas:
                        linha_limpa = linha.strip()

                        # 1. Identifica o início da linha com Data (Ex: 30/06/2025)
                        match_data = re.match(r'^(\d{2}/\d{2}/\d{4})\s+(.*)', linha_limpa)
                        if not match_data: continue

                        val_data = match_data.group(1)
                        resto = match_data.group(2)

                        # 2. Busca valores monetários na linha (Ex: -46,00 ou 33.000,00)
                        # Este padrão captura números com vírgula e ponto, com ou sem o sinal de negativo
                        matches_valor = list(re.finditer(r'-?[\d\.]*,\d{2}', resto))
                        if not matches_valor: continue

                        # O primeiro valor encontrado é sempre o da transação (o segundo, se houver, é o saldo)
                        val_str_raw = matches_valor[0].group(0)

                        eh_negativo = "-" in val_str_raw
                        val_clean = self.limpar_valor(val_str_raw.replace("-", ""))

                        if val_clean == 0: continue

                        tipo = "DEBITO" if eh_negativo else "CREDITO"
                        valor_final = -abs(val_clean) if eh_negativo else abs(val_clean)

                        # 3. Limpeza do Histórico (Subtração)
                        desc = resto
                        for m in matches_valor:
                            desc = desc.replace(m.group(0), "") # Remove o valor e o saldo

                        # Remove números de documentos longos (ex: 000000, 322169)
                        desc = re.sub(r'\b\d{5,}\b', '', desc)
                        desc = re.sub(r'\s+', ' ', desc).strip()

                        if "SALDO" in desc.upper(): continue
                        if not desc: desc = "HISTORICO NAO IDENTIFICADO"

                        registros.append({
                            "DATA": val_data,
                            "HISTORICO": self.remover_acentos(desc).upper(),
                            "VALOR": valor_final,
                            "TIPO": tipo
                        })

            # 4. Finalização
            if registros:
                df = self.preparar_dataframe(registros)
                if df is not None:
                    nome_base = os.path.splitext(arquivo)[0] + "_V2"
                    return self.salvar_arquivo(df, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação validada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar Santander V2 {arquivo}: {e}", "erro")
            return None