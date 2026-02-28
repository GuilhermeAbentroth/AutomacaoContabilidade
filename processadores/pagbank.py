import os
import re
import pdfplumber
import pandas as pd
from base_processor import BaseProcessor


class PagbankProcessor(BaseProcessor):
    def __init__(self, pasta_pdf, pasta_excel):
        super().__init__(pasta_pdf, pasta_excel)
        self.nome_banco = "PAGBANK"

    def _processar_transacao(self, buffer):
        """Método auxiliar interno para extrair os dados do buffer de texto"""
        if not buffer: return None

        # 1. Tenta pegar tudo apenas da PRIMEIRA linha
        linha_principal = buffer['linhas'][0].strip()
        match_vals = list(re.finditer(r'([-\u2010-\u2015\u2212]?\s*R\$\s*[\d\.,]+)', linha_principal))

        texto_usado = ""

        if match_vals:
            # CENÁRIO IDEAL: O valor está na primeira linha.
            texto_usado = linha_principal
        else:
            # CENÁRIO DE SEGURANÇA: Junta com a segunda linha para achar o dinheiro.
            texto_usado = " ".join(buffer['linhas']).replace('\n', ' ')
            match_vals = list(re.finditer(r'([-\u2010-\u2015\u2212]?\s*R\$\s*[\d\.,]+)', texto_usado))

        if not match_vals: return None  # Sem dinheiro, ignora.

        # Pega o último valor encontrado
        val_match = match_vals[-1]
        val_raw = val_match.group(1)

        # 2. SUBTRAÇÃO: Remove Data e Valor do Texto Selecionado
        desc = texto_usado.replace(buffer['data'], "")
        desc = desc.replace(val_raw, "")

        # Limpezas
        desc = re.sub(r'\s+', ' ', desc).strip()
        desc = desc.strip(" -–—.|")

        if "SALDO DO DIA" in desc.upper(): return None

        if not desc: desc = "PAGAMENTO"

        # 3. Processa Valor Numérico utilizando as ferramentas da Base
        val_norm = re.sub(r'[-\u2010-\u2015\u2212]', '-', val_raw)
        eh_neg = "-" in val_norm

        # Limpa usando o método Pai
        v_num = self.limpar_valor(val_norm)

        return {
            "DATA": buffer['data'],
            "HISTORICO": self.remover_acentos(desc).upper(),
            "VALOR": -abs(v_num) if eh_neg else abs(v_num),
            "TIPO": "DEBITO" if eh_neg else "CREDITO"
        }

    def processar(self, arquivo, log_func):
        """
        Lê e extrai os dados de um PDF do PagBank.
        Retorna o nome do ficheiro Excel gerado ou None em caso de falha.
        """
        log_func(f"Lendo PAGBANK: {arquivo}")
        caminho_pdf = os.path.join(self.pasta_pdf, arquivo)
        linhas_texto = []

        try:
            with pdfplumber.open(caminho_pdf) as pdf:
                for page in pdf.pages:
                    texto = page.extract_text()
                    if texto:
                        linhas_texto.extend(texto.split('\n'))

            if not linhas_texto:
                log_func(f"Aviso: PDF vazio ou imagem em {arquivo}", "erro")
                return None

            registros = []
            buffer = None

            for linha in linhas_texto:
                linha = linha.strip()
                if not linha: continue

                # Verifica se é o início de um novo lançamento (DATA)
                match_data = re.match(r'^(\d{2}/\d{2}/\d{4})', linha)

                if match_data:
                    # Se já existia um buffer aberto, salva-o antes de começar um novo
                    if buffer:
                        res = self._processar_transacao(buffer)
                        if res: registros.append(res)

                    # Abre novo buffer
                    buffer = {
                        "data": match_data.group(1),
                        "linhas": [linha]
                    }

                elif buffer:
                    # Guarda no buffer (linhas de continuação)
                    buffer["linhas"].append(linha)

            # Salva o último registo pendente
            if buffer:
                res = self._processar_transacao(buffer)
                if res: registros.append(res)

            # 4. Finalização e Gravação
            if registros:
                # O PagBank tem a peculiaridade de gerar duplicados na leitura, por isso filtramos antes
                df_temp = pd.DataFrame(registros).drop_duplicates()
                registros_unicos = df_temp.to_dict('records')

                # Prepara e salva usando a classe Pai
                df_final = self.preparar_dataframe(registros_unicos)
                if df_final is not None:
                    nome_base = os.path.splitext(arquivo)[0]
                    return self.salvar_arquivo(df_final, nome_base)
            else:
                log_func(f"Aviso: Nenhuma transação encontrada em {arquivo}", "erro")
                return None

        except Exception as e:
            log_func(f"Erro ao processar {arquivo}: {e}", "erro")
            return None