import pandas as pd
import os
from datetime import datetime
from openpyxl import load_workbook


class AutomationLogger:
    def __init__(self, pasta_exe):
        self.caminho_excel = os.path.join(pasta_exe, "log_eventos_automacao.xlsx")
        self.categorias_resumo = [
            "NFSE BAIXADAS",
            "XML BAIXADO",
            "EXTRATOS CONVERTIDOS PDF-EXCEL",
            "EXTRATOS CONVERTIDOS EXCEL-OFX",
            "NOTAS EMITIDAS (BETHA)",
            "ARQUIVOS UNIFICADOS"
        ]

    def registrar(self, modulo, categoria, descricao, quantidade=1):
        """
        modulo: 'CONTABIL', 'FISCAL', 'BETHBA', etc.
        categoria: Deve bater com as categorias_resumo para somar no dashboard
        """
        data_hoje = datetime.now().strftime("%d/%m/%Y")
        nova_linha = pd.DataFrame([{
            "Data": data_hoje,
            "Hora": datetime.now().strftime("%H:%M:%S"),
            "Categoria": categoria,
            "Descricao": descricao,
            "Quantidade": quantidade
        }])

        # Se o arquivo não existir, cria um novo
        if not os.path.exists(self.caminho_excel):
            with pd.ExcelWriter(self.caminho_excel, engine='openpyxl') as writer:
                nova_linha.to_excel(writer, sheet_name=modulo, index=False)
                # Cria um resumo vazio inicial
                resumo_df = pd.DataFrame({"Indicador": self.categorias_resumo, "Total": 0})
                resumo_df.to_excel(writer, sheet_name="RESUMO", index=False)
        else:
            # Se já existir, acrescenta na aba do módulo
            with pd.ExcelWriter(self.caminho_excel, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
                try:
                    # Tenta ler a aba existente para dar o append
                    df_existente = pd.read_excel(self.caminho_excel, sheet_name=modulo)
                    df_final = pd.concat([df_existente, nova_linha], ignore_index=True)
                    df_final.to_excel(writer, sheet_name=modulo, index=False)
                except Exception:
                    # Se a aba do módulo não existir ainda, cria ela
                    nova_linha.to_excel(writer, sheet_name=modulo, index=False)

        self._atualizar_resumo()

    def _atualizar_resumo(self):
        """Varre todas as abas (exceto RESUMO) e soma as quantidades por categoria"""
        xls = pd.ExcelFile(self.caminho_excel)
        abas = [sheet for sheet in xls.sheet_names if sheet != "RESUMO"]

        dados_todos = []
        for aba in abas:
            dados_todos.append(pd.read_excel(self.caminho_excel, sheet_name=aba))

        if not dados_todos: return

        df_total = pd.concat(dados_todos)

        # Agrupa e soma
        resumo = []
        for cat in self.categorias_resumo:
            total = df_total[df_total['Categoria'] == cat]['Quantidade'].sum()
            resumo.append({"Indicador": cat, "Total": total})

        df_resumo = pd.DataFrame(resumo)

        # Salva o resumo na primeira aba
        with pd.ExcelWriter(self.caminho_excel, engine='openpyxl', mode='a', if_sheet_exists='overlay') as writer:
            # Garante que o Resumo seja a primeira aba (Page 1)
            df_resumo.to_excel(writer, sheet_name="RESUMO", index=False)