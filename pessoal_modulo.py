import customtkinter as ctk
import tkinter as tk
from tkinter import messagebox, simpledialog
import os
import sqlite3
from datetime import date


class PessoalModulo:
    """
    Dashboard do módulo Pessoal: mostra, por competência (ano/mês), quais empresas
    tiveram NFS-e TOMADAS com retenções federais (INSS/IRRF/CSLL/PIS/COFINS) que
    precisam ser declaradas na REINF. Os dados são alimentados automaticamente pelo
    download de notas via certificado (NFSE via API Oficial → notas TOMADAS).
    """

    SENHA_ACESSO = "5794"

    MESES_PT = {
        1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril",
        5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
        9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro",
    }

    def __init__(self, parent):
        self.parent = parent
        self._autenticado = False

    # ------------------------------------------------------------------
    # Acesso
    # ------------------------------------------------------------------
    def abrir(self):
        if not self._autenticado:
            senha = simpledialog.askstring("Acesso Restrito — Pessoal", "Digite a senha do módulo:", show="*")
            if senha is None:
                return
            if senha != self.SENHA_ACESSO:
                messagebox.showerror("Erro", "Senha incorreta!")
                return
            self._autenticado = True
        self.tela_dashboard()

    # ------------------------------------------------------------------
    # Banco de dados
    # ------------------------------------------------------------------
    def _conectar_db(self):
        db_path = self.parent.configuracoes.get("caminho_banco")
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reinf_retencoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chave_acesso TEXT UNIQUE,
                empresa_cnpj TEXT,
                empresa_nome TEXT,
                competencia TEXT,
                numero_nfse TEXT,
                data_emissao TEXT,
                prestador_cnpj TEXT,
                prestador_nome TEXT,
                valor_servico REAL,
                valor_liquido REAL,
                v_inss REAL,
                v_irrf REAL,
                v_csll REAL,
                v_pis REAL,
                v_cofins REAL,
                v_total_retencoes REAL,
                status TEXT,
                caminho_pdf TEXT,
                caminho_xml TEXT,
                data_registro TEXT
            )
        """)
        return conn

    def _listar_empresas(self, competencia):
        conn = self._conectar_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT empresa_cnpj, empresa_nome, COUNT(*), SUM(v_total_retencoes)
            FROM reinf_retencoes
            WHERE competencia = ?
            GROUP BY empresa_cnpj, empresa_nome
            ORDER BY empresa_nome
        """, (competencia,))
        linhas = cur.fetchall()
        conn.close()
        return linhas

    def _listar_notas_empresa(self, empresa_cnpj, competencia):
        conn = self._conectar_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT numero_nfse, data_emissao, prestador_cnpj, prestador_nome, valor_servico,
                   v_inss, v_irrf, v_csll, v_pis, v_cofins, v_total_retencoes, status, caminho_pdf
            FROM reinf_retencoes
            WHERE empresa_cnpj = ? AND competencia = ?
            ORDER BY data_emissao, numero_nfse
        """, (empresa_cnpj, competencia))
        linhas = cur.fetchall()
        conn.close()
        return linhas

    # ------------------------------------------------------------------
    # Utilitários
    # ------------------------------------------------------------------
    def _fmt_money(self, v):
        try:
            return f"R$ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return "R$ 0,00"

    def _abrir_arquivo(self, caminho):
        if not caminho or not os.path.exists(caminho):
            messagebox.showwarning("Não encontrado", "O arquivo da nota não foi encontrado no caminho salvo.")
            return
        try:
            os.startfile(caminho)
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível abrir o arquivo:\n{e}")

    # ------------------------------------------------------------------
    # TELA — DASHBOARD (seleção de ano/mês + lista de empresas)
    # ------------------------------------------------------------------
    def tela_dashboard(self, ano=None, mes=None):
        self.parent.limpar_tela()

        hoje = date.today()
        mes_ant = hoje.month - 1 if hoje.month > 1 else 12
        ano_ant = hoje.year if hoje.month > 1 else hoje.year - 1
        ano = ano or ano_ant
        mes = mes or mes_ant

        f_header = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_header.pack(pady=5, fill="x")
        ctk.CTkLabel(f_header, text="👥 Pessoal — Retenções REINF",
                     font=("Arial", 20, "bold"), text_color="#16a085").pack(pady=5)
        ctk.CTkLabel(f_header,
                     text="Empresas com NFS-e tomadas que tiveram retenção federal (INSS/IRRF/CSLL/PIS/COFINS)\n"
                          "e precisam ser declaradas na REINF, por competência.",
                     font=("Arial", 12), text_color="gray").pack()

        f_filtro = ctk.CTkFrame(self.parent.container)
        f_filtro.pack(fill="x", padx=40, pady=10)

        ctk.CTkLabel(f_filtro, text="Competência:", font=("Arial", 12, "bold")).pack(side="left", padx=(15, 5), pady=12)

        combo_mes = ctk.CTkOptionMenu(f_filtro, values=list(self.MESES_PT.values()), width=140)
        combo_mes.set(self.MESES_PT[mes])
        combo_mes.pack(side="left", padx=5)

        ent_ano = ctk.CTkEntry(f_filtro, width=80)
        ent_ano.insert(0, str(ano))
        ent_ano.pack(side="left", padx=5)

        def buscar():
            try:
                ano_sel = int(ent_ano.get().strip())
                mes_sel = [k for k, v in self.MESES_PT.items() if v == combo_mes.get()][0]
            except Exception:
                messagebox.showwarning("Validação", "Informe um ano válido.")
                return
            self._carregar_empresas(f_lista, ano_sel, mes_sel)

        ctk.CTkButton(f_filtro, text="🔍 Buscar", command=buscar,
                      fg_color="#16a085", hover_color="#12876f", width=100).pack(side="left", padx=15)

        f_lista = ctk.CTkScrollableFrame(self.parent.container, fg_color="transparent")
        f_lista.pack(fill="both", expand=True, padx=40, pady=5)

        f_btns = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_btns.pack(pady=10)
        ctk.CTkButton(f_btns, text="Voltar ao Menu", command=self.parent.mostrar_menu_inicial,
                      width=150, height=40, fg_color="gray").pack()

        self._carregar_empresas(f_lista, ano, mes)

    def _carregar_empresas(self, container, ano, mes):
        for widget in container.winfo_children():
            widget.destroy()

        competencia = f"{ano:04d}-{mes:02d}"
        empresas = self._listar_empresas(competencia)

        if not empresas:
            ctk.CTkLabel(container, text="Nenhuma empresa com retenção REINF nesta competência.",
                         font=("Arial", 13), text_color="gray").pack(pady=30)
            return

        for cnpj, nome, qtd_notas, total_retido in empresas:
            card = ctk.CTkFrame(container, border_width=1, border_color="#16a085")
            card.pack(fill="x", pady=4, padx=5)

            f1 = ctk.CTkFrame(card, fg_color="transparent")
            f1.pack(fill="x", padx=15, pady=(10, 2))
            ctk.CTkLabel(f1, text=nome or "(sem nome)", font=("Arial", 14, "bold"), anchor="w").pack(side="left")

            f2 = ctk.CTkFrame(card, fg_color="transparent")
            f2.pack(fill="x", padx=15, pady=(0, 10))
            ctk.CTkLabel(f2, text=f"CNPJ: {cnpj}", font=("Arial", 11), text_color="gray").pack(side="left")
            ctk.CTkLabel(f2, text=f"  |  {qtd_notas} nota(s) com retenção",
                         font=("Arial", 11), text_color="gray").pack(side="left")
            ctk.CTkLabel(f2, text=f"  |  Total retido: {self._fmt_money(total_retido)}",
                         font=("Arial", 11, "bold"), text_color="#16a085").pack(side="left")

            ctk.CTkButton(f2, text="Abrir ▸", width=90,
                          fg_color="#16a085", hover_color="#12876f",
                          command=lambda c=cnpj, n=nome, a=ano, m=mes: self.tela_empresa(c, n, a, m)
                          ).pack(side="right", padx=5)

    # ------------------------------------------------------------------
    # TELA — EMPRESA (notas com retenção da competência)
    # ------------------------------------------------------------------
    def tela_empresa(self, cnpj, nome, ano, mes):
        self.parent.limpar_tela()

        competencia = f"{ano:04d}-{mes:02d}"

        f_header = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_header.pack(pady=5, fill="x")
        ctk.CTkLabel(f_header, text=f"👥 {nome}",
                     font=("Arial", 18, "bold"), text_color="#16a085").pack(pady=(5, 0))
        ctk.CTkLabel(f_header, text=f"CNPJ: {cnpj}  —  Competência: {self.MESES_PT[mes]}/{ano}",
                     font=("Arial", 12), text_color="gray").pack()

        f_lista = ctk.CTkScrollableFrame(self.parent.container, fg_color="transparent")
        f_lista.pack(fill="both", expand=True, padx=40, pady=10)

        notas = self._listar_notas_empresa(cnpj, competencia)

        if not notas:
            ctk.CTkLabel(f_lista, text="Nenhuma nota encontrada.", font=("Arial", 13), text_color="gray").pack(pady=30)
        else:
            total_geral = 0.0
            for (numero, dt_emi, prest_cnpj, prest_nome, v_serv, v_inss, v_irrf,
                 v_csll, v_pis, v_cofins, v_total, status, caminho_pdf) in notas:
                total_geral += (v_total or 0.0)

                card = ctk.CTkFrame(f_lista, border_width=1, border_color="#7f8c8d")
                card.pack(fill="x", pady=3, padx=5)

                f1 = ctk.CTkFrame(card, fg_color="transparent")
                f1.pack(fill="x", padx=12, pady=(8, 2))
                ctk.CTkLabel(f1, text=f"NF nº {numero}", font=("Arial", 12, "bold")).pack(side="left")
                ctk.CTkLabel(f1, text=f"  {prest_nome} ({prest_cnpj})",
                             font=("Arial", 11), text_color="gray").pack(side="left", padx=5)
                if status == "CANCELADA":
                    ctk.CTkLabel(f1, text="CANCELADA", font=("Arial", 10, "bold"),
                                 text_color="#c0392b").pack(side="right", padx=5)
                ctk.CTkLabel(f1, text=f"Emissão: {dt_emi}", font=("Arial", 10), text_color="gray").pack(side="right", padx=5)

                f2 = ctk.CTkFrame(card, fg_color="transparent")
                f2.pack(fill="x", padx=12, pady=(0, 2))
                ctk.CTkLabel(f2, text=f"Valor Serviço: {self._fmt_money(v_serv)}",
                             font=("Arial", 11)).pack(side="left", padx=(0, 15))
                for lbl, val in [("INSS", v_inss), ("IRRF", v_irrf), ("CSLL", v_csll),
                                  ("PIS", v_pis), ("COFINS", v_cofins)]:
                    if val and val > 0:
                        ctk.CTkLabel(f2, text=f"{lbl}: {self._fmt_money(val)}",
                                     font=("Arial", 11)).pack(side="left", padx=(0, 15))

                f3 = ctk.CTkFrame(card, fg_color="transparent")
                f3.pack(fill="x", padx=12, pady=(2, 8))
                ctk.CTkLabel(f3, text=f"Total Retido REINF: {self._fmt_money(v_total)}",
                             font=("Arial", 12, "bold"), text_color="#16a085").pack(side="left")
                ctk.CTkButton(f3, text="📄 Ver Nota", width=110, height=28,
                              fg_color="#27ae60", hover_color="#218c4e",
                              command=lambda p=caminho_pdf: self._abrir_arquivo(p)).pack(side="right")

            f_total = ctk.CTkFrame(self.parent.container)
            f_total.pack(fill="x", padx=40, pady=(0, 5))
            ctk.CTkLabel(f_total, text=f"Total geral retido na competência: {self._fmt_money(total_geral)}",
                         font=("Arial", 13, "bold"), text_color="#16a085").pack(pady=8)

        f_btns = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_btns.pack(pady=10)
        ctk.CTkButton(f_btns, text="◂ Voltar", command=lambda: self.tela_dashboard(ano, mes),
                      width=150, height=40, fg_color="gray").pack(side="left", padx=5)
        ctk.CTkButton(f_btns, text="Voltar ao Menu", command=self.parent.mostrar_menu_inicial,
                      width=150, height=40, fg_color="gray").pack(side="left", padx=5)
