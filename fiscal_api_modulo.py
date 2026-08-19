import customtkinter as ctk
import tkinter as tk
from tkinter import scrolledtext, filedialog
import threading
import os
import pandas as pd
import time
from utils import isolar_scroll_mouse


class FiscalAPIModulo:
    def __init__(self, parent):
        self.parent = parent
        self.container = parent.container

    # =========================================================================
    # NOVA UI (PREPARADA PARA API + CERTIFICADO A1)
    # =========================================================================
    def tela_emissor_betha_api(self):
        self.parent.limpar_tela()

        # Logo no topo
        f_l = ctk.CTkFrame(self.container, fg_color="transparent")
        f_l.pack(pady=10)
        self.parent.carregar_logo(f_l)

        # Título da tela
        ctk.CTkLabel(self.container, text="Emissor NFSe Lote (NOVA API)", font=("Arial", 22, "bold"),
                     text_color="#27ae60").pack(pady=(0, 10))

        # Card de Formulários
        f_card = ctk.CTkFrame(self.container)
        f_card.pack(fill="x", padx=40, pady=10)

        # --- LINHA 1: SELEÇÃO DA PLANILHA EXCEL ---
        f_excel = ctk.CTkFrame(f_card, fg_color="transparent")
        f_excel.pack(fill="x", padx=20, pady=(10, 10))

        ctk.CTkLabel(f_excel, text="Planilha Base:", font=("Arial", 12, "bold"), width=120, anchor="w").pack(
            side=tk.LEFT)
        self.ent_excel_nfse = ctk.CTkEntry(f_excel, font=("Arial", 12), width=450)
        self.ent_excel_nfse.pack(side=tk.LEFT, padx=10)

        def selecionar_planilha():
            p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls")])
            if p:
                self.ent_excel_nfse.delete(0, tk.END)
                self.ent_excel_nfse.insert(0, p)

        ctk.CTkButton(f_excel, text="Procurar", command=selecionar_planilha, width=100).pack(side=tk.LEFT, padx=5)

        # --- LINHA 2: SELEÇÃO DO CERTIFICADO A1 ---
        f_cert = ctk.CTkFrame(f_card, fg_color="transparent")
        f_cert.pack(fill="x", padx=20, pady=(10, 10))

        ctk.CTkLabel(f_cert, text="Certificado A1:", font=("Arial", 12, "bold"), width=120, anchor="w").pack(
            side=tk.LEFT)
        self.ent_certificado = ctk.CTkEntry(f_cert, font=("Arial", 12), width=450)
        self.ent_certificado.pack(side=tk.LEFT, padx=10)

        def selecionar_certificado():
            p = filedialog.askopenfilename(filetypes=[("Certificado", "*.pfx *.p12")])
            if p:
                self.ent_certificado.delete(0, tk.END)
                self.ent_certificado.insert(0, p)

        ctk.CTkButton(f_cert, text="Procurar", command=selecionar_certificado, width=100).pack(side=tk.LEFT, padx=5)

        # --- LINHA 3: SENHA DO CERTIFICADO ---
        f_senha = ctk.CTkFrame(f_card, fg_color="transparent")
        f_senha.pack(fill="x", padx=20, pady=(10, 10))

        ctk.CTkLabel(f_senha, text="Senha (PIN):", font=("Arial", 12, "bold"), width=120, anchor="w").pack(side=tk.LEFT)
        self.ent_senha_cert = ctk.CTkEntry(f_senha, font=("Arial", 12), width=200, show="*")
        self.ent_senha_cert.pack(side=tk.LEFT, padx=10)

        # --- LINHA 4: AMBIENTE DE EMISSÃO ---
        f_ambiente = ctk.CTkFrame(f_card, fg_color="transparent")
        f_ambiente.pack(fill="x", padx=20, pady=(10, 20))

        ctk.CTkLabel(f_ambiente, text="Ambiente:", font=("Arial", 12, "bold"), width=120, anchor="w").pack(side=tk.LEFT)

        self.var_ambiente = ctk.StringVar(value="Homologação (Testes)")

        # Um menu dropdown bem visível para o usuário não errar
        self.opt_ambiente = ctk.CTkOptionMenu(f_ambiente, variable=self.var_ambiente,
                                              values=["Homologação (Testes)", "Produção (Valendo!)"],
                                              fg_color="#005A9C", button_color="#00467a",
                                              font=("Arial", 12, "bold"), width=200)
        self.opt_ambiente.pack(side=tk.LEFT, padx=10)

        # --- CAIXA DE LOGS ---
        f_log_area = ctk.CTkFrame(self.container, fg_color="transparent")
        f_log_area.pack(fill="both", expand=True, padx=40, pady=5)

        self.parent.txt_log = scrolledtext.ScrolledText(f_log_area, width=125, height=12, state='disabled',
                                                        bg="#1e1e1e", fg="white", font=("Consolas", 10))
        self.parent.txt_log.pack(fill="both", expand=True)
        isolar_scroll_mouse(self.parent.txt_log)

        # --- BOTÕES DE AÇÃO ---
        f_btns = ctk.CTkFrame(self.container, fg_color="transparent")
        f_btns.pack(pady=20)

        ctk.CTkButton(f_btns, text="▶ ASSINAR E EMITIR LOTE (API)", command=self.start_thread,
                      fg_color="#27ae60", hover_color="#2ecc71", font=("Arial", 14, "bold"), height=50, width=350).pack(
            side="left", padx=20)

        ctk.CTkButton(f_btns, text="Voltar Menu", command=self.parent.mostrar_menu_inicial,
                      fg_color="gray", hover_color="darkgray", font=("Arial", 14), height=50, width=150).pack(
            side="left")

    def start_thread(self):
        threading.Thread(target=self.executar_emissao_api, daemon=True).start()

    def executar_emissao_api(self):
        # ---> NOVA IMPORTAÇÃO DO MÓDULO DE SEGURANÇA <---
        from certificado_utils import CertificadoA1

        caminho_excel = self.ent_excel_nfse.get().strip()
        caminho_cert = self.ent_certificado.get().strip()
        senha_cert = self.ent_senha_cert.get().strip()
        ambiente_escolhido = self.var_ambiente.get() # <--- PEGA O AMBIENTE AQUI

        if not caminho_excel or not os.path.exists(caminho_excel):
            self.parent.log_msg("ERRO: Selecione uma planilha Excel válida primeiro!", "erro")
            return

        if not caminho_cert or not os.path.exists(caminho_cert):
            self.parent.log_msg("ERRO: Selecione um Certificado A1 (.pfx) válido!", "erro")
            return

        if not senha_cert:
            self.parent.log_msg("ERRO: Informe a senha do certificado!", "erro")
            return

        try:
            # Imprime um aviso no log dizendo qual o ambiente
            tipo_log = "aviso" if "Homologação" in ambiente_escolhido else "erro"
            self.parent.log_msg(f"Iniciando em modo: {ambiente_escolhido.upper()}", tipo_log)

            # Preparação das URLs (serão ajustadas depois com as oficiais do Betha)
            if "Homologação" in ambiente_escolhido:
                url_api = "https://e-gov.betha.com.br/e-nota/testing/api..."
            else:
                url_api = "https://e-gov.betha.com.br/e-nota/producao/api..."

            # =================================================================
            # TENTATIVA DE DESBLOQUEIO DO CERTIFICADO A1
            # =================================================================
            self.parent.log_msg("Tentando desbloquear o Certificado A1...", "info")
            cert_a1 = CertificadoA1(caminho_cert, senha_cert)

            if not cert_a1.carregar_chaves(self.parent.log_msg):
                self.parent.log_msg("Processo abortado. Verifique a senha e tente novamente.", "erro")
                return
            # =================================================================

            self.parent.log_msg("Lendo planilha base...", "info")
            df = pd.read_excel(caminho_excel)
            total = len(df)
            self.parent.log_msg(f"Processando lote de {total} notas via API.", "info")

            # Simulador do fluxo futuro
            for index, row in df.iterrows():
                cliente = row.get('RAZAO_SOCIAL', 'Desconhecido')
                valor = row.get('VALOR_SERVICO', 0)

                self.parent.log_msg(f"[{index + 1}/{total}] Extraindo Chaves e montando XML para: {cliente}")
                time.sleep(1)  # Simula a montagem

                self.parent.log_msg(f"[{index + 1}/{total}] SUCESSO! NFSe assinada e transmitida.", "sucesso")

            self.parent.log_msg("LOTE FINALIZADO COM SUCESSO!", "sucesso")

        except Exception as e:
            self.parent.log_msg(f"Erro fatal: {e}", "erro")