import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, scrolledtext
import os
import time
import re
import threading
import requests
import warnings
from lxml import etree
from signxml import XMLSigner
from certificado_utils import CertificadoA1
from betha_database import BethaDatabase
from monitor_notas import MonitorNotas, TelaMonitor

# Silencia avisos técnicos do certificado
warnings.filterwarnings("ignore", category=UserWarning, message=".*PKCS#12 bundle could not be parsed.*")


class EmissorBethaManual:
    def __init__(self, parent):
        self.parent = parent
        self.db_path = self.parent.configuracoes.get("caminho_banco",
                                                     os.path.join(self.parent.pasta_exe, "dados_escritorio.db"))
        self.db = BethaDatabase(self.db_path)

        # Variáveis de controle interno
        self.prestador_id_atual = None
        self.prestador_cnpj_atual = None
        self.mapa_tomadores = {}
        # Cache da alíquota padrão do prestador (lida do cadastro)
        self.aliquota_padrao_prestador = ""
        self.prestador_nome_atual = ""
        self.loc_prestacao_ibge = ""
        self.loc_prestacao_nome = ""
        self.loc_prestacao_uf = ""
        self.nbs_prestador = ""

        # -------------------------------------------------------
        # Monitor de notas: acompanha protocolos pendentes e
        # baixa os PDFs automaticamente quando a prefeitura
        # conclui o processamento assíncrono.
        # -------------------------------------------------------
        pasta_pdfs = self.parent.configuracoes.get(
            "pasta_pdfs",
            os.path.join(self.parent.pasta_exe, "NFSe_PDFs")
        )
        self.monitor = MonitorNotas(
            db_path=self.db_path,
            pasta_pdfs=pasta_pdfs,
            log_fn=self.parent.log_msg
        )
        self.tela_monitor = TelaMonitor(self.parent, self.monitor)

    def tela_emissor_manual(self):
        self.parent.limpar_tela()

        # --- CABEÇALHO COMPACTO SEM LOGO ---
        f_header = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_header.pack(pady=5, fill="x")
        ctk.CTkLabel(f_header, text="✍️ Emissão Manual & Cadastro Inteligente", font=("Arial", 20, "bold"),
                     text_color="#27ae60").pack(pady=5)

        # --- CARD PRESTADOR (EMISSOR) ---
        f_prest = ctk.CTkFrame(self.parent.container)
        f_prest.pack(fill="x", padx=40, pady=5)

        ctk.CTkLabel(f_prest, text="PRESTADOR (EMISSOR)", font=("Arial", 11, "bold"), text_color="#1f538d").pack(pady=2)

        f_sel = ctk.CTkFrame(f_prest, fg_color="transparent")
        f_sel.pack(fill="x", padx=20, pady=3)

        lista_p = [p[0] for p in self.db.listar_prestadores()]
        if not lista_p:
            lista_p = ["Nenhum prestador cadastrado"]

        self.combo_p = ctk.CTkComboBox(f_sel, values=lista_p, width=320, command=self.ao_selecionar_prestador)
        self.combo_p.pack(side="left", padx=5)

        ctk.CTkButton(f_sel, text="+ Novo Prestador", width=120, fg_color="#1f538d", hover_color="#14375e",
                      command=self.janela_novo_prestador).pack(side="left", padx=5)

        # Atualizado para Editar Prestador
        self.btn_trocar_cert = ctk.CTkButton(f_sel, text="✏️ Editar Prestador", width=130,
                                             fg_color="#e67e22", hover_color="#d35400",
                                             state="disabled",
                                             command=self.janela_editar_prestador)
        self.btn_trocar_cert.pack(side="left", padx=5)

        self.btn_excluir_prest = ctk.CTkButton(f_sel, text="🗑️ Excluir", width=100, fg_color="#c0392b",
                                               hover_color="#962d22", state="disabled",
                                               command=self.excluir_prestador_logic)
        self.btn_excluir_prest.pack(side="left", padx=5)

        # --- CARD TOMADOR ---
        self.f_toma = ctk.CTkFrame(self.parent.container)
        self.f_toma.pack(fill="x", padx=40, pady=5)
        ctk.CTkLabel(self.f_toma, text="DADOS DO TOMADOR & TRIBUTAÇÃO", font=("Arial", 11, "bold"),
                     text_color="#1f538d").pack(pady=2)

        f_sel_toma = ctk.CTkFrame(self.f_toma, fg_color="transparent")
        f_sel_toma.pack(fill="x", padx=20, pady=3)
        ctk.CTkLabel(f_sel_toma, text="Selecionar Cliente:", font=("Arial", 12, "bold"), width=110, anchor="w").pack(
            side="left")

        self.combo_t = ctk.CTkComboBox(f_sel_toma, values=["Selecione um Prestador primeiro"], width=320,
                                       state="disabled", command=self.ao_selecionar_tomador)
        self.combo_t.pack(side="left", padx=5)

        self.btn_novo_toma = ctk.CTkButton(f_sel_toma, text="+ Novo Tomador", width=120, fg_color="#1f538d",
                                           state="disabled", command=self.preparar_novo_tomador)
        self.btn_novo_toma.pack(side="left", padx=5)

        self.btn_excluir_toma = ctk.CTkButton(f_sel_toma, text="🗑️ Excluir Cliente", width=120, fg_color="#c0392b",
                                              hover_color="#962d22", state="disabled",
                                              command=self.excluir_tomador_logic)
        self.btn_excluir_toma.pack(side="left", padx=5)

        # Grid de Campos do Formulário
        f_grid = ctk.CTkFrame(self.f_toma, fg_color="transparent")
        f_grid.pack(fill="x", padx=20, pady=3)

        def criar_campo_grid(parent, label, row, col, width_box=200):
            ctk.CTkLabel(parent, text=label, font=("Arial", 10, "bold")).grid(row=row, column=col, sticky="w", padx=5,
                                                                              pady=1)
            entry = ctk.CTkEntry(parent, width=width_box, height=26)
            entry.grid(row=row + 1, column=col, sticky="w", padx=5, pady=1)
            return entry

        self.ent_t_cnpj = criar_campo_grid(f_grid, "CPF/CNPJ do Tomador:", 0, 0, 140)
        self.btn_buscar_cnpj = ctk.CTkButton(
            f_grid, text="🔍", width=35, height=26,
            fg_color="#1f538d", hover_color="#14375e",
            command=self._auto_preencher_por_cnpj
        )
        self.btn_buscar_cnpj.grid(row=1, column=0, sticky="e", padx=(0, 5), pady=1)
        self.ent_t_nome = criar_campo_grid(f_grid, "Razão Social / Nome do Cliente:", 0, 1, 380)
        self.ent_t_email = criar_campo_grid(f_grid, "E-mail do Tomador:", 0, 2, 220)

        self.ent_t_cep = criar_campo_grid(f_grid, "CEP:", 2, 0, 140)
        ctk.CTkButton(f_grid, text="🔍", width=35, height=26,
                      fg_color="#1f538d", hover_color="#14375e",
                      command=self._buscar_cep_manual
                      ).grid(row=3, column=0, sticky="e", padx=(0, 5), pady=1)
        self.ent_t_end = criar_campo_grid(f_grid, "Endereço (Logradouro):", 2, 1, 380)
        self.ent_t_num = criar_campo_grid(f_grid, "Número:", 2, 2, 90)

        self.ent_t_comp = criar_campo_grid(f_grid, "Complemento:", 4, 0, 180)
        self.ent_t_bairro = criar_campo_grid(f_grid, "Bairro:", 4, 1, 180)
        self.ent_t_cidade = criar_campo_grid(f_grid, "Cidade:", 4, 2, 190)
        self.ent_t_uf = criar_campo_grid(f_grid, "UF:", 4, 3, 50)

        # --- LINHA DE VALORES E RETENÇÕES ---
        f_valor = ctk.CTkFrame(self.f_toma, fg_color="transparent")
        f_valor.pack(fill="x", padx=20, pady=5)

        ctk.CTkLabel(f_valor, text="Valor (R$):", font=("Arial", 12, "bold"), text_color="#27ae60", width=70,
                     anchor="w").pack(side="left")
        self.ent_v_servico = ctk.CTkEntry(f_valor, placeholder_text="0,00", width=100, font=("Arial", 12, "bold"),
                                          height=26)
        self.ent_v_servico.pack(side="left", padx=5)

        ctk.CTkLabel(f_valor, text="ISS Retido:", font=("Arial", 11, "bold"), width=70, anchor="e").pack(side="left",
                                                                                                         padx=(20, 5))
        self.combo_iss_nota = ctk.CTkComboBox(f_valor, values=["1 - Sim", "2 - Não"], width=90,
                                              state="readonly", command=self._toggle_aliq_iss)
        self.combo_iss_nota.pack(side="left", padx=5)
        self.combo_iss_nota.set("2 - Não")

        # Campo de alíquota do ISS
        ctk.CTkLabel(f_valor, text="Alíq. ISS (%):", font=("Arial", 11, "bold"), width=80, anchor="e").pack(
            side="left", padx=(10, 5))
        self.ent_aliq_iss = ctk.CTkEntry(f_valor, placeholder_text="Ex: 2.00", width=80,
                                         font=("Arial", 12), height=26)
        self.ent_aliq_iss.pack(side="left", padx=5)

        # Inserção manual de INSS (Contribuição Previdenciária)
        ctk.CTkLabel(f_valor, text="INSS (CP) (R$):", font=("Arial", 11, "bold"), width=90, anchor="e").pack(
            side="left", padx=(20, 5))
        self.ent_v_inss = ctk.CTkEntry(f_valor, placeholder_text="0,00", width=90, font=("Arial", 12), height=26)
        self.ent_v_inss.pack(side="left", padx=5)

        # Novo ComboBox Cód. Serviço (após INSS)
        ctk.CTkLabel(f_valor, text="Cód. Serviço:", font=("Arial", 11, "bold"),
                     width=90, anchor="e").pack(side="left", padx=(20, 5))
        self.combo_cod_servico = ctk.CTkComboBox(f_valor, values=[""], width=130, height=26,
                                                 state="readonly")
        self.combo_cod_servico.pack(side="left", padx=5)

        f_loc = ctk.CTkFrame(self.f_toma, fg_color="transparent")
        f_loc.pack(fill="x", padx=20, pady=3)

        ctk.CTkLabel(f_loc, text="Serviço Prestado Em:", font=("Arial", 11, "bold"),
                     width=130, anchor="w").pack(side="left")

        self.ent_loc_prestacao = ctk.CTkEntry(f_loc, placeholder_text="Digite a cidade...",
                                              width=280, height=26)
        self.ent_loc_prestacao.pack(side="left", padx=5)
        self.ent_loc_prestacao.bind("<KeyRelease>", self._buscar_cidades)

        self.lbl_loc_selecionada = ctk.CTkLabel(f_loc, text="", font=("Arial", 11),
                                                text_color="#27ae60", width=200, anchor="w")
        self.lbl_loc_selecionada.pack(side="left", padx=5)

        # Frame do dropdown de resultados
        self.frame_dropdown = ctk.CTkFrame(self.f_toma, fg_color="#2b2b2b", border_width=1)
        self.lista_cidades = ctk.CTkScrollableFrame(self.frame_dropdown, height=120)
        self.lista_cidades.pack(fill="x", padx=2, pady=2)

        f_cno = ctk.CTkFrame(self.f_toma, fg_color="transparent")
        f_cno.pack(fill="x", padx=20, pady=3)
        ctk.CTkLabel(f_cno, text="CNO (opcional):", font=("Arial", 11, "bold"),
                     width=130, anchor="w").pack(side="left")
        self.ent_cno = ctk.CTkEntry(f_cno,
                                    placeholder_text="Ex: 9002781667/72",
                                    width=180, height=26)
        self.ent_cno.pack(side="left", padx=5)
        ctk.CTkLabel(f_cno,
                     text="Cadastro Nacional de Obras — somente quando exigido",
                     font=("Arial", 10), text_color="gray").pack(side="left", padx=5)

        # --- ÁREA DE DESCRIÇÃO DA NOTA ---
        f_desc_area = ctk.CTkFrame(self.parent.container)
        f_desc_area.pack(fill="x", padx=40, pady=3)

        f_desc_header = ctk.CTkFrame(f_desc_area, fg_color="transparent")
        f_desc_header.pack(fill="x", padx=20, pady=1)
        ctk.CTkLabel(f_desc_header, text="Descrição do Serviço (Preenchimento Manual Obrigatório):",
                     font=("Arial", 11, "bold")).pack(side="left")
        self.lbl_contador = ctk.CTkLabel(f_desc_header, text="0/2000",
                                         font=("Arial", 10), text_color="gray")
        self.lbl_contador.pack(side="right")

        self.txt_desc = ctk.CTkTextbox(f_desc_area, height=60)
        self.txt_desc.pack(fill="x", padx=20, pady=3)
        self.txt_desc.bind("<KeyRelease>", self._atualizar_contador)

        # --- ÁREA DE LOG DE EVENTOS ---
        f_log = ctk.CTkFrame(self.parent.container)
        f_log.pack(fill="both", expand=True, padx=40, pady=5)
        ctk.CTkLabel(f_log, text="Log de Operação Manual:", font=("Arial", 11, "bold"), text_color="gray").pack(
            anchor="w", padx=15, pady=1)

        self.parent.txt_log = scrolledtext.ScrolledText(f_log, width=120, height=6, state='disabled', bg="#1e1e1e",
                                                        fg="white", font=("Consolas", 10))
        self.parent.txt_log.pack(padx=15, pady=2, fill="both", expand=True)

        # --- CONTROLES DE SAÍDA ---
        f_btns = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_btns.pack(pady=10)

        ctk.CTkButton(f_btns, text="🚀 EMITIR NFSE MANUAL", command=self.fluxo_emissao_manual, width=250, height=45,
                      font=("Arial", 14, "bold"), fg_color="#27ae60", hover_color="#218c4e").pack(side="left", padx=10)

        # Botão de acompanhamento de notas
        ctk.CTkButton(f_btns, text="📋 Acompanhar Notas", command=self.tela_monitor.abrir,
                      width=180, height=45, fg_color="#1f538d",
                      hover_color="#14375e").pack(side="left", padx=10)

        ctk.CTkButton(f_btns, text="Voltar ao Menu", width=140, height=45, fg_color="gray",
                      command=self.parent.mostrar_menu_inicial).pack(side="left")

        if lista_p and lista_p[0] != "Nenhum prestador cadastrado":
            self.combo_p.set(lista_p[0])
            self.ao_selecionar_prestador(lista_p[0])

    def _consultar_cep(self, cep):
        try:
            resp = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=5)
            if resp.status_code == 200:
                dados = resp.json()
                if dados.get("erro"):
                    self.parent.root.after(0, lambda: self.parent.log_msg(
                        f"CEP {cep} não encontrado.", "erro"))
                    return
                self.parent.root.after(0, lambda: self._preencher_endereco(dados))
            else:
                self.parent.root.after(0, lambda: self.parent.log_msg(
                    f"Erro ao consultar CEP (HTTP {resp.status_code}).", "erro"))
        except Exception:
            self.parent.root.after(0, lambda: self.parent.log_msg(
                "Sem conexão — não foi possível consultar o CEP.", "erro"))

    def _auto_preencher_por_cnpj(self, event=None):
        """Busca dados cadastrais do tomador em outros prestadores ao sair do campo CNPJ."""
        cnpj = "".join(filter(str.isdigit, self.ent_t_cnpj.get()))
        if len(cnpj) not in (11, 14):
            return

        # Se o tomador já está carregado no combo atual, não faz nada
        if self.combo_t.get() and self.combo_t.get() in self.mapa_tomadores:
            t = self.mapa_tomadores[self.combo_t.get()]
            if "".join(filter(str.isdigit, str(t[2]))) == cnpj:
                return

        # Busca em outros prestadores
        dados = self.db.buscar_tomador_por_cnpj_global(cnpj)
        if not dados:
            return

        razao, cep, logradouro, numero, complemento, bairro, cidade, uf, email = dados

        # Preenche apenas campos vazios — não sobrescreve o que já foi digitado
        def preencher(entry, valor):
            if not entry.get() and valor:
                entry.delete(0, tk.END)
                entry.insert(0, str(valor).upper() if valor else "")

        def preencher_lower(entry, valor):
            if not entry.get() and valor:
                entry.delete(0, tk.END)
                entry.insert(0, str(valor).lower() if valor else "")

        preencher(self.ent_t_nome, razao)
        preencher(self.ent_t_cep, cep)
        preencher(self.ent_t_end, logradouro)
        preencher(self.ent_t_num, numero)
        preencher(self.ent_t_comp, complemento)
        preencher(self.ent_t_bairro, bairro)
        preencher(self.ent_t_cidade, cidade)
        preencher(self.ent_t_uf, uf)
        preencher_lower(self.ent_t_email, email)

        self.parent.log_msg(
            f"Dados cadastrais de '{razao}' importados de outro prestador.", "info")

    def _buscar_cep_manual(self):
        """Chamado pelo botão 🔍 — busca o CEP e preenche o endereço."""
        cep = "".join(filter(str.isdigit, self.ent_t_cep.get()))
        if len(cep) != 8:
            self.parent.log_msg("CEP inválido — deve conter 8 dígitos.", "erro")
            return
        self.parent.log_msg(f"Buscando CEP {cep}...", "info")
        threading.Thread(target=self._consultar_cep, args=(cep,), daemon=True).start()

    def _preencher_endereco(self, dados):
        """Preenche os campos de endereço com os dados do ViaCEP."""
        self.ent_t_end.delete(0, tk.END)
        self.ent_t_end.insert(0, dados.get("logradouro", "").upper())

        self.ent_t_bairro.delete(0, tk.END)
        self.ent_t_bairro.insert(0, dados.get("bairro", "").upper())

        self.ent_t_cidade.delete(0, tk.END)
        self.ent_t_cidade.insert(0, dados.get("localidade", "").upper())

        self.ent_t_uf.delete(0, tk.END)
        self.ent_t_uf.insert(0, dados.get("uf", "").upper())

        self.parent.log_msg(
            f"CEP {dados.get('cep', '')} → {dados.get('localidade', '')} - {dados.get('uf', '')} ✅",
            "sucesso")

    def _ler_aliquota_padrao_do_banco(self, dados_p):
        """Lê a alíquota diretamente do índice 12 (aliquota_iss) do cadastro do prestador."""
        try:
            v = dados_p[12]
            if v is None:
                return "2.00"
            s = str(v).strip().replace(',', '.')
            if not s or s in ('0', '0.0', '0.00'):
                return "2.00"
            f = float(s)
            if 0 < f <= 100:
                return f"{f:.2f}"
        except (IndexError, ValueError, AttributeError, TypeError):
            pass
        return "2.00"

    def _toggle_aliq_iss(self, valor):
        self.ent_aliq_iss.configure(state="normal")
        self.ent_aliq_iss.delete(0, tk.END)
        if self.aliquota_padrao_prestador:
            self.ent_aliq_iss.insert(0, self.aliquota_padrao_prestador)
        self.ent_aliq_iss.focus()

    def ao_selecionar_prestador(self, nome_escolhido):
        if nome_escolhido == "Nenhum prestador cadastrado":
            return

        self.btn_trocar_cert.configure(state="normal")
        self.btn_excluir_prest.configure(state="normal")
        self.btn_novo_toma.configure(state="normal")
        self.combo_t.configure(state="normal")

        for p in self.db.listar_prestadores():
            if p[0] == nome_escolhido:
                dados_p = self.db.buscar_dados_prestador(p[1])
                self.prestador_id_atual = dados_p[0]
                self.prestador_cnpj_atual = str(dados_p[1]).strip()
                self.prestador_nome_atual = nome_escolhido

                self.aliquota_padrao_prestador = self._ler_aliquota_padrao_do_banco(dados_p)

                # Popula o combo de serviço
                codigos = [c.strip() for c in str(dados_p[8]).split(";") if c.strip()]
                self.combo_cod_servico.configure(values=codigos if codigos else [""])
                if codigos:
                    self.combo_cod_servico.set(codigos[0])

                self.nbs_prestador = str(dados_p[13]).strip() if len(dados_p) > 13 and dados_p[13] else ""

                self.combo_iss_nota.set("2 - Não")
                self._toggle_aliq_iss("2 - Não")
                break

        self.atualizar_combo_tomadores()
        self.parent.log_msg(f"Empresa emissora selecionada: {nome_escolhido}", "info")
        if self.aliquota_padrao_prestador:
            self.parent.log_msg(f"Alíquota do cadastro: {self.aliquota_padrao_prestador}%", "info")
        else:
            self.parent.log_msg(
                "Aviso: alíquota não encontrada no cadastro. Preencha manualmente antes de emitir.", "erro")

    def atualizar_combo_tomadores(self):
        if not self.prestador_id_atual:
            return

        lista_t = self.db.buscar_tomadores_por_prestador(self.prestador_id_atual)
        self.mapa_tomadores = {str(t[3]): t for t in lista_t}

        nomes_t = [str(t[3]) for t in lista_t]
        self.combo_t.configure(values=nomes_t)
        self.combo_t.set("")
        self.btn_excluir_toma.configure(state="disabled")
        self.limpar_campos_tomador()

    def ao_selecionar_tomador(self, nome_escolhido):
        if nome_escolhido not in self.mapa_tomadores:
            return
        t = self.mapa_tomadores[nome_escolhido]
        self.limpar_campos_tomador()

        self.ent_t_cnpj.insert(0, str(t[2]))
        self.ent_t_nome.insert(0, str(t[3]))
        self.ent_t_cep.insert(0, str(t[4]))
        self.ent_t_end.insert(0, str(t[5]))
        self.ent_t_num.insert(0, str(t[6]))
        self.ent_t_comp.insert(0, str(t[7]) if t[7] else "")
        self.ent_t_bairro.insert(0, str(t[8]))
        self.ent_t_cidade.insert(0, str(t[9]))
        self.ent_t_uf.insert(0, str(t[10]))
        self.ent_t_email.insert(0, str(t[11]) if t[11] else "")

        self.btn_excluir_toma.configure(state="normal")
        self.parent.log_msg(f"Dados do tomador carregados: {nome_escolhido}", "info")

        loc_ibge = str(t[12]) if len(t) > 12 and t[12] else ""
        loc_nome = str(t[13]) if len(t) > 13 and t[13] else ""
        loc_uf = str(t[14]) if len(t) > 14 and t[14] else ""

        self.loc_prestacao_ibge = loc_ibge
        self.loc_prestacao_nome = loc_nome
        self.loc_prestacao_uf = loc_uf

        self.ent_loc_prestacao.delete(0, tk.END)
        if loc_nome:
            self.ent_loc_prestacao.insert(0, loc_nome)
            self.lbl_loc_selecionada.configure(text=f"- {loc_uf}  ✅")
        else:
            self.lbl_loc_selecionada.configure(text="")

        ultimo_cod = str(t[15]) if len(t) > 15 and t[15] else ""
        if ultimo_cod and ultimo_cod in self.combo_cod_servico.cget("values"):
            self.combo_cod_servico.set(ultimo_cod)

        ultimo_iss_aliq = str(t[16]) if len(t) > 16 and t[16] else ""
        ultimo_iss_ret = str(t[17]) if len(t) > 17 and t[17] else ""
        self.ent_aliq_iss.configure(state="normal")
        self.ent_aliq_iss.delete(0, tk.END)
        self.ent_aliq_iss.insert(0, ultimo_iss_aliq or self.aliquota_padrao_prestador)

        # Pré-preenche retenção do último ISS usado
        if ultimo_iss_ret == "1":
            self.combo_iss_nota.set("1 - Sim")
        elif ultimo_iss_ret == "2":
            self.combo_iss_nota.set("2 - Não")

    def preparar_novo_tomador(self):
        self.combo_t.set("")
        self.limpar_campos_tomador()
        self.btn_excluir_toma.configure(state="disabled")
        self.ent_t_cnpj.focus()
        self.parent.log_msg("Campos limpos. Pronto para receber novo cliente.", "info")
        self._limpar_loc_prestacao()

    def _atualizar_contador(self, event=None):
        """Atualiza o contador de caracteres da descrição em tempo real."""
        texto = " | ".join(
            linha.strip() for linha in
            self.txt_desc.get("1.0", "end").strip().upper().splitlines()
            if linha.strip()
        )
        total = len(texto)
        restante = 2000 - total

        if total > 2000:
            self.lbl_contador.configure(text=f"{total}/2000 ⚠️", text_color="#c0392b")
        elif total > 1800:
            self.lbl_contador.configure(text=f"{total}/2000", text_color="#e67e22")
        else:
            self.lbl_contador.configure(text=f"{total}/2000", text_color="gray")

    def limpar_campos_tomador(self):
        campos = [self.ent_t_cnpj, self.ent_t_nome, self.ent_t_cep, self.ent_t_end,
                  self.ent_t_num, self.ent_t_comp, self.ent_t_bairro, self.ent_t_cidade,
                  self.ent_t_uf, self.ent_t_email]
        for c in campos:
            c.delete(0, tk.END)

    def _buscar_cidades(self, event=None):
        termo = self.ent_loc_prestacao.get().strip()
        if len(termo) < 3:
            self.frame_dropdown.pack_forget()
            return
        threading.Thread(target=self._consultar_ibge, args=(termo,), daemon=True).start()

    def _consultar_ibge(self, termo):
        try:
            url = f"https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
            resp = requests.get(url, timeout=8)
            if resp.status_code != 200:
                return
            cidades = resp.json()
            termo_lower = termo.lower()
            resultado = [
                c for c in cidades
                if termo_lower in c['nome'].lower()
            ][:10]
            self.parent.root.after(0, lambda: self._exibir_dropdown(resultado))
        except Exception:
            pass

    def _exibir_dropdown(self, cidades):
        for w in self.lista_cidades.winfo_children():
            w.destroy()

        if not cidades:
            self.frame_dropdown.pack_forget()
            return

        self.frame_dropdown.pack(fill="x", padx=20, pady=0)
        self.frame_dropdown.lift()

        for cidade in cidades:
            nome = cidade['nome']
            uf = cidade['microrregiao']['mesorregiao']['UF']['sigla']
            ibge = str(cidade['id'])
            texto = f"{nome} - {uf}"

            btn = ctk.CTkButton(
                self.lista_cidades, text=texto,
                anchor="w", fg_color="transparent",
                hover_color="#3a3a3a", height=28,
                font=("Arial", 11),
                command=lambda n=nome, u=uf, i=ibge: self._selecionar_cidade(n, u, i)
            )
            btn.pack(fill="x", pady=1)

    def _selecionar_cidade(self, nome, uf, ibge):
        self.loc_prestacao_ibge = ibge
        self.loc_prestacao_nome = nome
        self.loc_prestacao_uf = uf

        self.ent_loc_prestacao.delete(0, tk.END)
        self.ent_loc_prestacao.insert(0, nome)
        self.lbl_loc_selecionada.configure(text=f"- {uf}  ✅")
        self.frame_dropdown.pack_forget()

    def _limpar_loc_prestacao(self):
        self.loc_prestacao_ibge = ""
        self.loc_prestacao_nome = ""
        self.loc_prestacao_uf = ""
        self.ent_loc_prestacao.delete(0, tk.END)
        self.lbl_loc_selecionada.configure(text="")

    def fluxo_emissao_manual(self):
        if not self.prestador_id_atual or not self.prestador_cnpj_atual:
            self.parent.log_msg("Erro: Nenhum prestador selecionado para emissão.", "erro")
            return

        t_dados = {
            "cnpj_cpf": "".join(filter(str.isdigit, self.ent_t_cnpj.get())),
            "razao_social": self.ent_t_nome.get().strip().upper(),
            "cep": "".join(filter(str.isdigit, self.ent_t_cep.get())),
            "logradouro": self.ent_t_end.get().strip().upper(),
            "numero": self.ent_t_num.get().strip().upper(),
            "complemento": self.ent_t_comp.get().strip().upper(),
            "bairro": self.ent_t_bairro.get().strip().upper(),
            "cidade": self.ent_t_cidade.get().strip().upper(),
            "uf": self.ent_t_uf.get().strip().upper(),
            "email": self.ent_t_email.get().strip().lower(),
            "ultimo_cod_servico": self.combo_cod_servico.get().strip()

        }

        if not t_dados["cnpj_cpf"] or not t_dados["razao_social"] \
                or not self.ent_v_servico.get() \
                or not self.txt_desc.get("1.0", tk.END).strip():
            self.parent.log_msg("Erro de validação: CNPJ, Razão Social, Valor e Descrição são obrigatórios.", "erro")
            return

        try:
            self.db.salvar_tomador(self.prestador_id_atual, t_dados)
            self.atualizar_combo_tomadores()
            self.combo_t.set(t_dados["razao_social"])
            self.btn_excluir_toma.configure(state="normal")

            self.parent.log_msg(f"Base de Dados: Cliente '{t_dados['razao_social']}' verificado/salvo com sucesso.",
                                "sucesso")

            valor_formatado = f"{float(str(self.ent_v_servico.get()).replace(',', '.')):.2f}"
            descricao_nota = " | ".join(
                linha.strip() for linha in
                self.txt_desc.get("1.0", tk.END).strip().upper().splitlines()
                if linha.strip()
            )
            if not descricao_nota:
                self.parent.log_msg("Erro: Descrição do serviço é obrigatória.", "erro")
                return
            if len(descricao_nota) > 2000:
                self.parent.log_msg(
                    f"Erro: Descrição muito longa ({len(descricao_nota)} caracteres). "
                    f"Máximo permitido: 2000 caracteres.", "erro")
                return

            iss_nota_override = self.combo_iss_nota.get().split(" - ")[0]
            reg_ap_trib_sn = "2" if iss_nota_override == "1" else "1"
            iss_eh_retido = (iss_nota_override == "1")

            v_aliq_raw = self.ent_aliq_iss.get().replace(',', '.').strip()
            if not v_aliq_raw:
                self.parent.log_msg(
                    "Erro: Alíquota do ISS é obrigatória. Preencha o cadastro do prestador "
                    "ou informe manualmente.", "erro")
                return
            try:
                aliq_iss_formatada = f"{float(v_aliq_raw):.2f}"
                if float(aliq_iss_formatada) <= 0:
                    self.parent.log_msg("Erro: Alíquota do ISS deve ser maior que zero.", "erro")
                    return
            except ValueError:
                self.parent.log_msg("Erro: Alíquota do ISS inválida. Use formato numérico (Ex: 2.00).", "erro")
                return

            v_inss_raw = self.ent_v_inss.get().replace(',', '.').strip()
            if not v_inss_raw:
                v_inss_raw = "0"
            try:
                inss_formatado = f"{float(v_inss_raw):.2f}"
            except ValueError:
                self.parent.log_msg("Erro: Valor do INSS (CP) inválido. Digite apenas números.", "erro")
                return
            if not self.loc_prestacao_ibge:
                self.parent.log_msg(
                    "Erro: Selecione a cidade onde o serviço foi prestado.", "erro")
                return

            t_dados["loc_prestacao_ibge"] = self.loc_prestacao_ibge
            t_dados["loc_prestacao_nome"] = self.loc_prestacao_nome
            t_dados["loc_prestacao_uf"] = self.loc_prestacao_uf

            cod_servico_selecionado = self.combo_cod_servico.get().strip()
            if not cod_servico_selecionado:
                self.parent.log_msg("Erro: Selecione o código de serviço.", "erro")
                return
            t_dados["ultimo_cod_servico"] = cod_servico_selecionado
            t_dados["ultimo_iss_aliquota"] = aliq_iss_formatada
            t_dados["ultimo_iss_retido"] = iss_nota_override

            cno = self.ent_cno.get().strip()
            t_dados["cno"] = cno

            threading.Thread(
                target=self._executar_transmissao_soap,
                args=(self.prestador_cnpj_atual, t_dados, valor_formatado, descricao_nota,
                      iss_eh_retido, inss_formatado, aliq_iss_formatada, reg_ap_trib_sn),
                daemon=True
            ).start()

        except Exception as e:
            self.parent.log_msg(f"Falha operacional ao processar cadastro: {e}", "erro")

    def _auto_preencher_por_cnpj(self, event=None):
        cnpj = "".join(filter(str.isdigit, self.ent_t_cnpj.get()))
        if len(cnpj) not in (11, 14):
            return

        # Se tomador já está carregado no combo atual, não faz nada
        if self.combo_t.get() and self.combo_t.get() in self.mapa_tomadores:
            t = self.mapa_tomadores[self.combo_t.get()]
            if "".join(filter(str.isdigit, str(t[2]))) == cnpj:
                return

        # Busca primeiro no banco local
        dados_local = self.db.buscar_tomador_por_cnpj_global(cnpj)
        if dados_local:
            razao, cep, logradouro, numero, complemento, bairro, cidade, uf, email = dados_local

            def preencher(entry, valor):
                if not entry.get() and valor:
                    entry.delete(0, tk.END)
                    entry.insert(0, str(valor).upper())

            def preencher_lower(entry, valor):
                if not entry.get() and valor:
                    entry.delete(0, tk.END)
                    entry.insert(0, str(valor).lower())

            preencher(self.ent_t_nome, razao)
            preencher(self.ent_t_cep, cep)
            preencher(self.ent_t_end, logradouro)
            preencher(self.ent_t_num, numero)
            preencher(self.ent_t_comp, complemento)
            preencher(self.ent_t_bairro, bairro)
            preencher(self.ent_t_cidade, cidade)
            preencher(self.ent_t_uf, uf)
            preencher_lower(self.ent_t_email, email)
            self.parent.log_msg(
                f"Dados de '{razao}' importados do cadastro local.", "info")
            return

        # Se CNPJ (14 dígitos) e não está no banco, consulta Receita Federal via BrasilAPI
        if len(cnpj) == 14:
            self.parent.log_msg(f"Consultando CNPJ {cnpj}...", "info")
            if hasattr(self, 'btn_buscar_cnpj'):
                self.btn_buscar_cnpj.configure(state="disabled", text="⏳")
            threading.Thread(
                target=self._consultar_cnpj_api, args=(cnpj,), daemon=True
            ).start()

    def _consultar_cnpj_api(self, cnpj: str):
        """Consulta CNPJ via publica.cnpj.ws (dados oficiais da Receita Federal)."""

        def re_habilitar():
            if hasattr(self, 'btn_buscar_cnpj'):
                self.btn_buscar_cnpj.configure(state="normal", text="🔍")

        try:
            resp = requests.get(
                f"https://publica.cnpj.ws/cnpj/{cnpj}",
                timeout=10,
                headers={"Accept": "application/json"}
            )
            if resp.status_code == 200:
                raw = resp.json()
                est = raw.get("estabelecimento", {})
                dados = {
                    "razao_social": raw.get("razao_social", ""),
                    "cep": (est.get("cep") or "").replace("-", "").replace(".", ""),
                    "logradouro": est.get("logradouro", ""),
                    "numero": est.get("numero", ""),
                    "complemento": est.get("complemento", "") or "",
                    "bairro": est.get("bairro", ""),
                    "municipio": (est.get("cidade") or {}).get("nome", ""),
                    "uf": (est.get("estado") or {}).get("sigla", ""),
                    "email": est.get("email", "") or "",
                    "cnae_fiscal": (est.get("atividade_principal") or {})
                    .get("id", "").replace(".", "").replace("-", ""),
                    "descricao_situacao_cadastral": est.get("situacao_cadastral", ""),
                }
                self.parent.root.after(0, lambda: self._preencher_dados_cnpj(dados))

            elif resp.status_code == 429:
                self.parent.root.after(0, lambda: self.parent.log_msg(
                    "Muitas consultas seguidas. Aguarde alguns segundos e tente novamente.", "erro"))
            elif resp.status_code == 404:
                self.parent.root.after(0, lambda: self.parent.log_msg(
                    f"CNPJ {cnpj} não encontrado na Receita Federal.", "info"))
            else:
                self.parent.root.after(0, lambda: self.parent.log_msg(
                    f"Erro ao consultar CNPJ (HTTP {resp.status_code}).", "erro"))

        except requests.exceptions.ConnectionError:
            self.parent.root.after(0, lambda: self.parent.log_msg(
                "Sem conexão — verifique a internet.", "erro"))
        except Exception as e:
            self.parent.root.after(0, lambda: self.parent.log_msg(
                f"Erro inesperado: {e}", "erro"))
        finally:
            self.parent.root.after(0, re_habilitar)

    def _preencher_dados_cnpj(self, dados: dict):
        """Preenche os campos do formulário com os dados da Receita Federal."""

        def preencher(entry, valor):
            if valor:
                entry.delete(0, tk.END)
                entry.insert(0, str(valor).strip().upper())

        def preencher_lower(entry, valor):
            if valor:
                entry.delete(0, tk.END)
                entry.insert(0, str(valor).strip().lower())

        preencher(self.ent_t_nome, dados.get('razao_social', ''))
        preencher(self.ent_t_cep, dados.get('cep', '').replace('-', '').replace('.', ''))
        preencher(self.ent_t_end, dados.get('logradouro', ''))
        preencher(self.ent_t_num, dados.get('numero', ''))
        preencher(self.ent_t_comp, dados.get('complemento', ''))
        preencher(self.ent_t_bairro, dados.get('bairro', ''))
        preencher(self.ent_t_cidade, dados.get('municipio', ''))
        preencher(self.ent_t_uf, dados.get('uf', ''))
        preencher_lower(self.ent_t_email, dados.get('email', ''))

        razao = dados.get('razao_social', 'Empresa')
        situacao = dados.get('descricao_situacao_cadastral', '')
        if situacao and situacao.upper() != 'ATIVA':
            self.parent.log_msg(
                f"⚠️ CNPJ situação: {situacao} — verifique antes de emitir.", "erro")
        else:
            self.parent.log_msg(
                f"✅ Dados de '{razao}' preenchidos via Receita Federal.", "sucesso")

    def _executar_transmissao_soap(self, cnpj_prestador, tomador, valor, descricao,
                                   iss_eh_retido, v_inss, aliq_iss, reg_ap_trib_sn):

        cep_limpo = tomador["cep"].replace("-", "").strip()
        cmun_tomador = "0000000"
        try:
            resp_cep = requests.get(f"https://viacep.com.br/ws/{cep_limpo}/json/", timeout=5)
            if resp_cep.status_code == 200:
                dados_cep = resp_cep.json()
                cmun_tomador = dados_cep.get("ibge", "0000000")
                self.parent.log_msg(
                    f"Município do tomador: {dados_cep.get('localidade', '?')} - IBGE: {cmun_tomador}", "info")
        except Exception:
            self.parent.log_msg("Aviso: não foi possível consultar o CEP do tomador. Usando código IBGE genérico.",
                                "erro")

        url_ws = "https://nota-eletronica.betha.cloud/dps/ws"
        tp_amb = "1"

        try:
            p_dados = self.db.buscar_dados_prestador(cnpj_prestador)
            im_p = str(p_dados[2]).strip()
            caminho_pfx = str(p_dados[4]).strip()
            senha_pfx = str(p_dados[5]).strip()
            nbs = str(p_dados[13]).strip() if len(p_dados) > 13 and p_dados[13] else "101011200"

            item_lista = tomador.get("ultimo_cod_servico", "").replace('.', '').ljust(6, '0') \
                         or str(p_dados[8]).replace('.', '').ljust(6, '0')

            self.parent.log_msg("Abrindo cofre de segurança... Inicializando Certificado Digital A1.", "info")
            cert_manager = CertificadoA1(caminho_pfx, senha_pfx)
            if not cert_manager.carregar_chaves(self.parent.log_msg):
                return
        except Exception as e:
            self.parent.log_msg(f"Erro Crítico ao carregar dados do prestador/certificado: {e}", "erro")
            return

        try:
            tempo_seguro = time.time() - 300
            dh_emi = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(tempo_seguro))
            dt_comp = time.strftime('%Y-%m-%d', time.localtime(tempo_seguro))

            num_v = str(int(time.time() * 1000) % 1000000000000000).zfill(15)
            id_45 = f"DPS42089062{cnpj_prestador.zfill(14)}{'900'.zfill(5)}{num_v}"

            servico_final = descricao
            if tomador.get("cno"):
                servico_final = f"{descricao} | CNO {tomador['cno']}"

            dados_xml = {
                "id_45": id_45, "dhEmi": dh_emi, "dCompet": dt_comp, "valor": valor,
                "cnpj_tomador": tomador["cnpj_cpf"], "cep_tomador": tomador["cep"],
                "cmun_tomador": cmun_tomador,
                "email_tomador": tomador.get("email", "").strip(),
                "logradouro": tomador["logradouro"][:80], "numero": tomador["numero"][:10],
                "bairro": tomador["bairro"][:60], "razao_social": tomador["razao_social"][:150],
                "servico": descricao,  # ← era servico_final, agora só descricao
                "item_lista": item_lista,
                "cnpj_prest": cnpj_prestador, "im_prest": im_p,
                "nDPS": num_v.lstrip('0') or "1",
                "iss_eh_retido": iss_eh_retido, "inss": v_inss,
                "aliq_iss": aliq_iss,
                "reg_ap_trib_sn": reg_ap_trib_sn,
                "loc_prestacao_ibge": tomador.get("loc_prestacao_ibge", "4208906"),
                "nbs": nbs,
                "cno": tomador.get("cno", ""),
            }

            self.parent.log_msg(f"Empacotando e assinando XML da DPS número {dados_xml['nDPS']}...")
            xml_corpo = self._gerar_xml_dps_corpo(dados_xml, tp_amb)

            root = etree.fromstring(xml_corpo.encode('utf-8'))
            signed_root = XMLSigner().sign(root, key=cert_manager.obter_chave_privada_pem(),
                                           cert=cert_manager.obter_certificado_pem())
            xml_assinado = etree.tostring(signed_root, encoding='utf-8', xml_declaration=False)

            xml_limpo = xml_assinado.decode('utf-8') \
                .replace('<?xml version="1.0" encoding="UTF-8"?>', '') \
                .replace('<?xml version="1.0" ?>', '').strip()

            envelope = (
                '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
                'xmlns="http://www.betha.com.br/e-nota-dps">'
                f'<soapenv:Body><RecepcionarDpsEnvio>{xml_limpo}</RecepcionarDpsEnvio></soapenv:Body>'
                '</soapenv:Envelope>'
            )

            self.parent.log_msg("Transmitindo lote manual seguro para a Betha Cloud...", "info")
            resp = requests.post(url_ws, data=envelope.encode('utf-8'),
                                 headers={'Content-Type': 'text/xml;charset=UTF-8'}, timeout=60)

            if resp.status_code == 200:
                prot_match = re.search(r'protocolo>(.*?)</', resp.text, re.IGNORECASE)
                if prot_match:
                    protocolo = prot_match.group(1).strip()
                    self.parent.log_msg(
                        f"SUCESSO! Lote recebido pela prefeitura. Protocolo: {protocolo}", "sucesso")
                    self.parent.estatisticas.registrar_evento("nota_emitida")

                    nome_prestador = self.prestador_nome_atual or cnpj_prestador
                    self.monitor.registrar_pendente(
                        protocolo=protocolo,
                        cnpj_prestador=cnpj_prestador,
                        nome_tomador=tomador["razao_social"],
                        nome_prestador=nome_prestador
                    )
                    self.monitor.salvar_xml_emissao(xml_limpo, protocolo, nome_prestador)
                else:
                    msg_match = re.search(r'mensagem>(.*?)</', resp.text, re.IGNORECASE)
                    self.parent.log_msg(
                        f"REJEITADA PELA PREFEITURA: "
                        f"{msg_match.group(1) if msg_match else 'Erro estrutural betha'}", "erro")
            else:
                self.parent.log_msg(f"Erro de comunicação de rede HTTP {resp.status_code}", "erro")

        except Exception as e:
            self.parent.log_msg(f"Erro Crítico de transmissão SOAP: {e}", "erro")

    def _gerar_xml_dps_corpo(self, d, tp_amb):
        bloco_inss = (
            f"<tribFed><vRetCP>{d['inss']}</vRetCP></tribFed>"
            if float(d['inss']) > 0 else ""
        )

        bloco_cno = f"""<obra>
                                <cObra>{d['cno']}</cObra>
                            </obra>""" if d.get('cno') else ""

        valor_tp_ret_issqn = "2" if d['iss_eh_retido'] else "1"

        doc_tomador = (
            f"<CPF>{d['cnpj_tomador']}</CPF>"
            if len(d['cnpj_tomador']) == 11
            else f"<CNPJ>{d['cnpj_tomador']}</CNPJ>"
        )

        bloco_email_tomador = (
            f"<email>{d['email_tomador']}</email>"
            if d.get('email_tomador') else ""
        )

        return f"""<DPS xmlns="http://www.betha.com.br/e-nota-dps" versao="1.01">
            <infDPS id="{d['id_45']}">
                <tpAmb>{tp_amb}</tpAmb>
                <dhEmi>{d['dhEmi']}</dhEmi>
                <verAplic>Abentroth_v6.9</verAplic>
                <serie>900</serie>
                <nDPS>{d['nDPS']}</nDPS>
                <dCompet>{d['dCompet']}</dCompet>
                <tpEmit>1</tpEmit>
                <cLocEmi>4208906</cLocEmi>
                <prest>
                    <CNPJ>{d['cnpj_prest']}</CNPJ>
                    <IM>{d['im_prest']}</IM>
                    <regTrib>
                        <opSimpNac>3</opSimpNac>
                        <regApTribSN>{d['reg_ap_trib_sn']}</regApTribSN>
                        <regEspTrib>0</regEspTrib>
                    </regTrib>
                </prest>
                <toma>
                    {doc_tomador}
                    <xNome>{d['razao_social']}</xNome>
                    <end>
                        <endNac><cMun>{d['cmun_tomador']}</cMun><CEP>{d['cep_tomador']}</CEP></endNac>
                        <xLgr>{d['logradouro']}</xLgr>
                        <nro>{d['numero']}</nro>
                        <xBairro>{d['bairro']}</xBairro>
                    </end>
                    {bloco_email_tomador}
                </toma>
                <serv>
                    <locPrest><cLocPrestacao>{d['loc_prestacao_ibge']}</cLocPrestacao></locPrest>
                    <cServ>
                        <cTribNac>{d['item_lista']}</cTribNac>
                        <xDescServ>{d['servico']}</xDescServ>
                        <cNBS>{d['nbs']}</cNBS>
                    </cServ>
                    {bloco_cno}
                </serv>
                <valores>
                    <vServPrest><vServ>{d['valor']}</vServ></vServPrest>
                    <trib>
                        <tribMun>
                            <tribISSQN>1</tribISSQN>
                            <pAliq>{d['aliq_iss']}</pAliq>
                            <tpRetISSQN>{valor_tp_ret_issqn}</tpRetISSQN>
                        </tribMun>
                        {bloco_inss}
                        <totTrib>
                            <pTotTrib>
                                <pTotTribFed>0.00</pTotTribFed>
                                <pTotTribEst>0.00</pTotTribEst>
                                <pTotTribMun>0.00</pTotTribMun>
                            </pTotTrib>
                        </totTrib>
                    </trib>
                </valores>
            </infDPS>
        </DPS>"""

    def excluir_prestador_logic(self):
        nome_p = self.combo_p.get()
        if not nome_p or nome_p == "Nenhum prestador cadastrado":
            return
        confirmar = messagebox.askyesno(
            "⚠️ EXCLUSÃO CRÍTICA",
            f"Deseja deletar '{nome_p}'?\n\nIsto apagará a empresa e TODOS os clientes vinculados a ela na rede!")
        if confirmar:
            try:
                for p in self.db.listar_prestadores():
                    if p[0] == nome_p:
                        self.db.excluir_prestador(p[1])
                        self.parent.log_msg(f"Removido: Prestador '{nome_p}' excluído da rede.", "erro")
                        lista_atualizada = [pr[0] for pr in self.db.listar_prestadores()]
                        if not lista_atualizada:
                            lista_atualizada = ["Nenhum prestador cadastrado"]
                            self.prestador_id_atual = None
                            self.combo_p.configure(values=lista_atualizada)
                            self.combo_p.set(lista_atualizada[0])
                            self.btn_trocar_cert.configure(state="disabled")
                            self.btn_excluir_prest.configure(state="disabled")
                            self.btn_novo_toma.configure(state="disabled")
                            self.combo_t.configure(state="disabled")
                            self.combo_t.set("Selecione um Prestador primeiro")
                            self.limpar_campos_tomador()
                        else:
                            self.combo_p.configure(values=lista_atualizada)
                            self.combo_p.set(lista_atualizada[0])
                            self.ao_selecionar_prestador(lista_atualizada[0])
                        return
            except Exception as e:
                self.parent.log_msg(f"Erro ao deletar prestador: {e}", "erro")

    def excluir_tomador_logic(self):
        nome_t = self.combo_t.get()
        if not nome_t or nome_t not in self.mapa_tomadores:
            return
        if messagebox.askyesno("Confirmar Exclusão", f"Deseja remover o cliente '{nome_t}' da base?"):
            try:
                t = self.mapa_tomadores[nome_t]
                self.db.excluir_tomador(self.prestador_id_atual, t[2])
                self.parent.log_msg(f"Removido: Cadastro do cliente '{nome_t}' deletado.", "erro")
                self.atualizar_combo_tomadores()
            except Exception as e:
                self.parent.log_msg(f"Erro ao deletar tomador: {e}", "erro")

    def janela_editar_prestador(self):
        nome_p = self.combo_p.get()
        if not nome_p or nome_p == "Nenhum prestador cadastrado":
            return
        # Busca dados atuais
        dados_p = None
        for p in self.db.listar_prestadores():
            if p[0] == nome_p:
                dados_p = self.db.buscar_dados_prestador(p[1])
                break
        if not dados_p:
            return

        janela_cadastro = ctk.CTkToplevel(self.parent.root)
        janela_cadastro.title(f"Editar Prestador — {nome_p}")
        janela_cadastro.geometry("600x700")
        janela_cadastro.resizable(False, False)
        janela_cadastro.transient(self.parent.root)
        janela_cadastro.grab_set()

        ctk.CTkLabel(janela_cadastro, text="Editar Prestador", font=("Arial", 16, "bold"),
                     text_color="#e67e22").pack(pady=10)

        f_campos = ctk.CTkScrollableFrame(janela_cadastro, fg_color="transparent")
        f_campos.pack(fill="both", expand=True, padx=30, pady=5)

        def criar_campo(label, valor="", placeholder=""):
            f_linha = ctk.CTkFrame(f_campos, fg_color="transparent")
            f_linha.pack(fill="x", pady=4)
            ctk.CTkLabel(f_linha, text=label, font=("Arial", 12, "bold"),
                         width=200, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(f_linha, placeholder_text=placeholder, width=300)
            entry.insert(0, valor)
            entry.pack(side="left", padx=10)
            return entry

        def criar_combobox(label, valores, valor_atual):
            f_linha = ctk.CTkFrame(f_campos, fg_color="transparent")
            f_linha.pack(fill="x", pady=4)
            ctk.CTkLabel(f_linha, text=label, font=("Arial", 12, "bold"),
                         width=200, anchor="w").pack(side="left")
            combo = ctk.CTkComboBox(f_linha, values=valores, width=300, state="readonly")
            combo.set(valor_atual)
            combo.pack(side="left", padx=10)
            return combo

        # índices: 0=id, 1=cnpj, 2=im, 3=nome, 4=pfx, 5=senha,
        #          6=cnae, 7=cod_servico, 8=item_lista, 9=exig,
        #          10=natureza, 11=iss_retido, 12=aliquota
        ent_nome = criar_campo("Razão Social / Nome:", str(dados_p[3] or ""))
        f_cnpj_row = ctk.CTkFrame(f_campos, fg_color="transparent")
        f_cnpj_row.pack(fill="x", pady=4)
        ctk.CTkLabel(f_cnpj_row, text="CNPJ:", font=("Arial", 12, "bold"),
                     width=200, anchor="w").pack(side="left")
        ent_cnpj = ctk.CTkEntry(f_cnpj_row, width=240)
        ent_cnpj.insert(0, str(dados_p[1] or ""))
        ent_cnpj.pack(side="left", padx=10)
        btn_cnpj_edit = ctk.CTkButton(f_cnpj_row, text="🔍", width=40, height=28,
                                      fg_color="#1f538d", hover_color="#14375e",
                                      command=lambda: _buscar_cnpj_editar())
        btn_cnpj_edit.pack(side="left", padx=5)

        def _buscar_cnpj_editar():
            cnpj = "".join(filter(str.isdigit, ent_cnpj.get()))
            if len(cnpj) != 14:
                return
            btn_cnpj_edit.configure(state="disabled", text="⏳")

            def consultar():
                try:
                    resp = requests.get(f"https://publica.cnpj.ws/cnpj/{cnpj}",
                                        timeout=10, headers={"Accept": "application/json"})
                    if resp.status_code == 200:
                        raw = resp.json()
                        est = raw.get("estabelecimento", {})
                        cnae = (est.get("atividade_principal") or {}).get("id", "").replace(".", "").replace("-", "")

                        def preencher():
                            # Na edição sempre atualiza
                            if raw.get("razao_social"):
                                ent_nome.delete(0, tk.END)
                                ent_nome.insert(0, raw.get("razao_social", "").upper())
                            if cnae:
                                ent_cnae.delete(0, tk.END)
                                ent_cnae.insert(0, cnae)
                            btn_cnpj_edit.configure(state="normal", text="🔍")

                        janela_cadastro.after(0, preencher)
                    else:
                        janela_cadastro.after(0, lambda: btn_cnpj_edit.configure(state="normal", text="🔍"))
                except Exception:
                    janela_cadastro.after(0, lambda: btn_cnpj_edit.configure(state="normal", text="🔍"))

            threading.Thread(target=consultar, daemon=True).start()

        ent_im = criar_campo("Inscrição Municipal:", str(dados_p[2] or ""))
        ent_cnae = criar_campo("Código CNAE:", str(dados_p[6] or ""))
        ent_item = criar_campo("Códigos de Serviço (separe por ;):",
                               str(dados_p[8] or ""), "Ex: 170201;170501")
        ent_aliq = criar_campo("Alíquota ISS (%):", str(dados_p[12] or ""))
        ent_nbs = criar_campo("NBS (Nomencl. Bras. Serviços):",
                              str(dados_p[13]) if len(dados_p) > 13 and dados_p[13] else "")

        exig_opcoes = ["1 - Exigível", "2 - Não incidência", "3 - Isenção",
                       "4 - Exportação", "5 - Imunidade",
                       "6 - Susp. Decisão Judicial", "7 - Susp. Proc. Administrativo"]
        exig_atual = next((o for o in exig_opcoes
                           if o.startswith(str(dados_p[9] or "1"))), exig_opcoes[0])
        ent_exig = criar_combobox("Exigibilidade ISS:", exig_opcoes, exig_atual)

        ret_atual = "1 - Sim" if str(dados_p[11]) == "1" else "2 - Não"
        ent_ret = criar_combobox("ISS Retido:", ["1 - Sim", "2 - Não"], ret_atual)

        # Certificado
        f_cert = ctk.CTkFrame(f_campos, fg_color="transparent")
        f_cert.pack(fill="x", pady=4)
        ctk.CTkLabel(f_cert, text="Certificado (.pfx):", font=("Arial", 12, "bold"),
                     width=200, anchor="w").pack(side="left")
        ent_pfx = ctk.CTkEntry(f_cert, width=210)
        ent_pfx.insert(0, str(dados_p[4] or ""))
        ent_pfx.pack(side="left", padx=10)

        def buscar_pfx():
            caminho = filedialog.askopenfilename(filetypes=[("Certificado A1", "*.pfx")])
            if caminho:
                ent_pfx.delete(0, tk.END)
                ent_pfx.insert(0, caminho)

        ctk.CTkButton(f_cert, text="...", width=80, command=buscar_pfx).pack(side="left")
        ent_senha = criar_campo("Senha Certificado:")
        ent_senha.configure(show="*")

        def salvar_edicao():
            dados = {
                "nome": ent_nome.get().strip().upper(),
                "cnpj": "".join(filter(str.isdigit, ent_cnpj.get())),
                "im": ent_im.get().strip(),
                "cnae": ent_cnae.get().strip(),
                "servico": ent_item.get().strip(),
                "item": ent_item.get().strip(),
                "exigibilidade": ent_exig.get().split(" - ")[0],
                "natureza": "2",
                "iss_retido": ent_ret.get().split(" - ")[0],
                "aliquota": ent_aliq.get().strip(),
                "nbs": ent_nbs.get().strip(),
                "pfx": ent_pfx.get().strip() or str(dados_p[4]),
                "senha": ent_senha.get() or str(dados_p[5])
            }
            if not dados["nome"] or not dados["cnpj"]:
                messagebox.showwarning("Validação", "Nome e CNPJ são obrigatórios.",
                                       parent=janela_cadastro)
                return
            try:
                self.db.salvar_prestador(dados)
                messagebox.showinfo("Sucesso", "Prestador atualizado sem perder clientes!",
                                    parent=janela_cadastro)
                lista_atualizada = [p[0] for p in self.db.listar_prestadores()]
                self.combo_p.configure(values=lista_atualizada)
                self.combo_p.set(dados["nome"])
                self.ao_selecionar_prestador(dados["nome"])
                janela_cadastro.destroy()
            except Exception as e:
                messagebox.showerror("Erro", f"Falha ao salvar: {e}", parent=janela_cadastro)

        f_pop_btns = ctk.CTkFrame(janela_cadastro, fg_color="transparent")
        f_pop_btns.pack(pady=20)
        ctk.CTkButton(f_pop_btns, text="💾 Salvar Alterações", width=180, height=40,
                      fg_color="#e67e22", hover_color="#d35400",
                      command=salvar_edicao).pack(side="left", padx=10)
        ctk.CTkButton(f_pop_btns, text="Cancelar", width=120, height=40,
                      fg_color="gray", command=janela_cadastro.destroy).pack(side="left", padx=10)

    def janela_novo_prestador(self):
        janela_cadastro = ctk.CTkToplevel(self.parent.root)
        janela_cadastro.title("Cadastrar Novo Prestador (Emitente)")
        janela_cadastro.geometry("600x750")
        janela_cadastro.resizable(False, False)
        janela_cadastro.transient(self.parent.root)
        janela_cadastro.grab_set()

        ctk.CTkLabel(janela_cadastro, text="Cadastro de Regras Fiscais - Prestador", font=("Arial", 16, "bold"),
                     text_color="#1f538d").pack(pady=10)

        f_campos = ctk.CTkScrollableFrame(janela_cadastro, fg_color="transparent")
        f_campos.pack(fill="both", expand=True, padx=30, pady=5)

        def criar_campo(label, placeholder=""):
            f_linha = ctk.CTkFrame(f_campos, fg_color="transparent")
            f_linha.pack(fill="x", pady=4)
            ctk.CTkLabel(f_linha, text=label, font=("Arial", 12, "bold"), width=200, anchor="w").pack(side="left")
            entry = ctk.CTkEntry(f_linha, placeholder_text=placeholder, width=300)
            entry.pack(side="left", padx=10)
            return entry

        def criar_combobox(label, valores):
            f_linha = ctk.CTkFrame(f_campos, fg_color="transparent")
            f_linha.pack(fill="x", pady=4)
            ctk.CTkLabel(f_linha, text=label, font=("Arial", 12, "bold"), width=200, anchor="w").pack(side="left")
            combo = ctk.CTkComboBox(f_linha, values=valores, width=300, state="readonly")
            combo.pack(side="left", padx=10)
            return combo

        ent_nome = criar_campo("Razão Social / Nome:", "Ex: EMPRESA LTDA...")
        f_cnpj_row = ctk.CTkFrame(f_campos, fg_color="transparent")
        f_cnpj_row.pack(fill="x", pady=4)
        ctk.CTkLabel(f_cnpj_row, text="CNPJ (Apenas números):", font=("Arial", 12, "bold"),
                     width=200, anchor="w").pack(side="left")
        ent_cnpj = ctk.CTkEntry(f_cnpj_row, placeholder_text="Ex: 12345678000101", width=240)
        ent_cnpj.pack(side="left", padx=10)
        btn_cnpj_novo = ctk.CTkButton(f_cnpj_row, text="🔍", width=40, height=28,
                                      fg_color="#1f538d", hover_color="#14375e",
                                      command=lambda: _buscar_cnpj_novo())
        btn_cnpj_novo.pack(side="left", padx=5)
        ent_im = criar_campo("Inscrição Municipal:", "Ex: 12345")
        ent_cnae = criar_campo("Código CNAE:", "Ex: 8211300")

        # Campo de Item alterado conforme Issue 2 & 3
        ent_item = criar_campo("Códigos de Serviço (separe por ;):", "Ex: 170201;170501")

        def _buscar_cnpj_novo():
            cnpj = "".join(filter(str.isdigit, ent_cnpj.get()))
            if len(cnpj) != 14:
                return
            btn_cnpj_novo.configure(state="disabled", text="⏳")

            def consultar():
                try:
                    resp = requests.get(f"https://publica.cnpj.ws/cnpj/{cnpj}",
                                        timeout=10, headers={"Accept": "application/json"})
                    if resp.status_code == 200:
                        raw = resp.json()
                        est = raw.get("estabelecimento", {})
                        cnae = (est.get("atividade_principal") or {}).get("id", "").replace(".", "").replace("-", "")

                        def preencher():
                            if not ent_nome.get():
                                ent_nome.delete(0, tk.END)
                                ent_nome.insert(0, raw.get("razao_social", "").upper())
                            if not ent_cnae.get():
                                ent_cnae.delete(0, tk.END)
                                ent_cnae.insert(0, cnae)
                            btn_cnpj_novo.configure(state="normal", text="🔍")

                        janela_cadastro.after(0, preencher)
                    else:
                        janela_cadastro.after(0, lambda: btn_cnpj_novo.configure(state="normal", text="🔍"))
                except Exception:
                    janela_cadastro.after(0, lambda: btn_cnpj_novo.configure(state="normal", text="🔍"))

            threading.Thread(target=consultar, daemon=True).start()

        ent_exig = criar_combobox("Exigibilidade ISS:", [
            "1 - Exigível", "2 - Não incidência", "3 - Isenção",
            "4 - Exportação", "5 - Imunidade",
            "6 - Susp. Decisão Judicial", "7 - Susp. Proc. Administrativo"
        ])
        ent_exig.set("1 - Exigível")

        ent_nat = criar_combobox("Natureza Operação:", ["1 - Sim", "2 - Não"])
        ent_nat.set("2 - Não")

        ent_ret = criar_combobox("ISS Retido:", ["1 - Sim", "2 - Não"])
        ent_ret.set("2 - Não")

        ent_aliq = criar_campo("Alíquota ISS (%):", "Ex: 2.00")
        ent_nbs = criar_campo("NBS (Nomencl. Bras. Serviços):", "Ex: 101011200")

        f_cert = ctk.CTkFrame(f_campos, fg_color="transparent")
        f_cert.pack(fill="x", pady=4)
        ctk.CTkLabel(f_cert, text="Certificado (.pfx):", font=("Arial", 12, "bold"), width=200, anchor="w").pack(
            side="left")
        ent_pfx = ctk.CTkEntry(f_cert, width=210)
        ent_pfx.pack(side="left", padx=10)

        def buscar_pfx():
            caminho = filedialog.askopenfilename(filetypes=[("Certificado A1", "*.pfx")])
            if caminho:
                ent_pfx.delete(0, tk.END)
                ent_pfx.insert(0, caminho)

        ctk.CTkButton(f_cert, text="...", width=80, command=buscar_pfx).pack(side="left")
        ent_senha = criar_campo("Senha Certificado:")
        ent_senha.configure(show="*")

        def salvar_no_banco():
            dados = {
                "nome": ent_nome.get().strip().upper(),
                "cnpj": "".join(filter(str.isdigit, ent_cnpj.get())),
                "im": ent_im.get().strip(),
                "cnae": ent_cnae.get().strip(),
                "servico": ent_item.get().strip(),  # Alterado conf. Issue 2&3
                "item": ent_item.get().strip(),  # Alterado conf. Issue 2&3
                "exigibilidade": ent_exig.get().split(" - ")[0],
                "natureza": ent_nat.get().split(" - ")[0],
                "iss_retido": ent_ret.get().split(" - ")[0],
                "aliquota": ent_aliq.get().strip(),
                "nbs": ent_nbs.get().strip(),
                "pfx": ent_pfx.get().strip(),
                "senha": ent_senha.get()
            }
            if not dados["nome"] or not dados["cnpj"] or not dados["pfx"] or not dados["senha"]:
                messagebox.showwarning("Validação",
                                       "Os campos Nome, CNPJ, Arquivo PFX e Senha são obrigatórios.",
                                       parent=janela_cadastro)
                return
            try:
                self.db.salvar_prestador(dados)
                messagebox.showinfo("Sucesso", f"Empresa {dados['nome']} cadastrada!", parent=janela_cadastro)
                lista_atualizada = [p[0] for p in self.db.listar_prestadores()]
                self.combo_p.configure(values=lista_atualizada)
                self.combo_p.set(dados["nome"])
                self.ao_selecionar_prestador(dados["nome"])
                janela_cadastro.destroy()
            except Exception as e:
                messagebox.showerror("Erro", f"Falha na gravação do SQLite: {e}", parent=janela_cadastro)

        f_pop_btns = ctk.CTkFrame(janela_cadastro, fg_color="transparent")
        f_pop_btns.pack(pady=20)
        ctk.CTkButton(f_pop_btns, text="💾 Salvar Emitente", width=180, height=40, fg_color="#27ae60",
                      command=salvar_no_banco).pack(side="left", padx=10)
        ctk.CTkButton(f_pop_btns, text="Cancelar", width=120, height=40, fg_color="gray",
                      command=janela_cadastro.destroy).pack(side="left", padx=10)