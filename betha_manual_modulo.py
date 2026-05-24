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

        self.btn_trocar_cert = ctk.CTkButton(f_sel, text="🔄 Certificado", width=110, fg_color="#e67e22",
                                             hover_color="#d35400", state="disabled",
                                             command=self.trocar_certificado_logic)
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

        self.ent_t_cnpj = criar_campo_grid(f_grid, "CPF/CNPJ do Tomador:", 0, 0, 180)
        self.ent_t_nome = criar_campo_grid(f_grid, "Razão Social / Nome do Cliente:", 0, 1, 380)
        self.ent_t_email = criar_campo_grid(f_grid, "E-mail do Tomador:", 0, 2, 220)

        self.ent_t_cep = criar_campo_grid(f_grid, "CEP:", 2, 0, 180)
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

        # Campo de alíquota do ISS — sempre editável, pré-preenchido com
        # a alíquota do cadastro do prestador.
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

        # --- ÁREA DE DESCRIÇÃO DA NOTA ---
        f_desc_area = ctk.CTkFrame(self.parent.container)
        f_desc_area.pack(fill="x", padx=40, pady=3)
        ctk.CTkLabel(f_desc_area, text="Descrição do Serviço (Preenchimento Manual Obrigatório):",
                     font=("Arial", 11, "bold")).pack(padx=20, anchor="w", pady=1)
        self.txt_desc = ctk.CTkTextbox(f_desc_area, height=60)
        self.txt_desc.pack(fill="x", padx=20, pady=3)

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

    # ------------------------------------------------------------------
    # Heurística defensiva para ler a alíquota padrão do cadastro do
    # prestador, sem depender do índice exato do schema do banco.
    # ------------------------------------------------------------------
    def _ler_aliquota_padrao_do_banco(self, dados_p):
        candidatos_prioritarios = (9, 10, 7, 6, 12, 13)
        for idx in candidatos_prioritarios:
            try:
                v = dados_p[idx]
                if v is None:
                    continue
                s = str(v).strip().replace(',', '.')
                if not s or s in ('0', '0.0', '0.00'):
                    continue
                f = float(s)
                if 0 < f <= 10:
                    return f"{f:.2f}"
            except (IndexError, ValueError, AttributeError, TypeError):
                continue
        for idx in range(len(dados_p)):
            if idx in candidatos_prioritarios:
                continue
            try:
                v = dados_p[idx]
                if v is None:
                    continue
                s = str(v).strip().replace(',', '.')
                if not s or s in ('0', '0.0', '0.00'):
                    continue
                f = float(s)
                if 0 < f <= 10:
                    return f"{f:.2f}"
            except (IndexError, ValueError, AttributeError, TypeError):
                continue
        return ""

    # ------------------------------------------------------------------
    # Campo de alíquota: sempre editável, pré-preenchido com o cadastro
    # ------------------------------------------------------------------
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

    def preparar_novo_tomador(self):
        self.combo_t.set("")
        self.limpar_campos_tomador()
        self.btn_excluir_toma.configure(state="disabled")
        self.ent_t_cnpj.focus()
        self.parent.log_msg("Campos limpos. Pronto para receber novo cliente.", "info")

    def limpar_campos_tomador(self):
        campos = [self.ent_t_cnpj, self.ent_t_nome, self.ent_t_cep, self.ent_t_end,
                  self.ent_t_num, self.ent_t_comp, self.ent_t_bairro, self.ent_t_cidade,
                  self.ent_t_uf, self.ent_t_email]
        for c in campos:
            c.delete(0, tk.END)

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
            "email": self.ent_t_email.get().strip().lower()
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
            descricao_nota = self.txt_desc.get("1.0", tk.END).strip().upper()

            iss_nota_override = self.combo_iss_nota.get().split(" - ")[0]
            reg_ap_trib_sn = "2" if iss_nota_override == "1" else "1"
            iss_eh_retido = (iss_nota_override == "1")

            # Alíquota — obrigatória sempre
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

            threading.Thread(
                target=self._executar_transmissao_soap,
                args=(self.prestador_cnpj_atual, t_dados, valor_formatado, descricao_nota,
                      iss_eh_retido, inss_formatado, aliq_iss_formatada, reg_ap_trib_sn),
                daemon=True
            ).start()

        except Exception as e:
            self.parent.log_msg(f"Falha operacional ao processar cadastro: {e}", "erro")

    def _executar_transmissao_soap(self, cnpj_prestador, tomador, valor, descricao,
                                   iss_eh_retido, v_inss, aliq_iss, reg_ap_trib_sn):

        # Consulta o código IBGE do município do tomador via ViaCEP
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

        p_dados = self.db.buscar_dados_prestador(cnpj_prestador)
        im_p = str(p_dados[2]).strip()
        caminho_pfx = str(p_dados[4]).strip()
        senha_pfx = str(p_dados[5]).strip()
        item_lista = str(p_dados[8]).replace('.', '').ljust(6, '0')

        self.parent.log_msg("Abrindo cofre de segurança... Inicializando Certificado Digital A1.", "info")
        cert_manager = CertificadoA1(caminho_pfx, senha_pfx)
        if not cert_manager.carregar_chaves(self.parent.log_msg):
            return

        try:
            tempo_seguro = time.time() - 300
            dh_emi = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(tempo_seguro))
            dt_comp = time.strftime('%Y-%m-%d', time.localtime(tempo_seguro))

            num_v = str(int(time.time() * 1000) % 1000000000000000).zfill(15)
            id_45 = f"DPS42089062{cnpj_prestador.zfill(14)}{'900'.zfill(5)}{num_v}"

            dados_xml = {
                "id_45": id_45, "dhEmi": dh_emi, "dCompet": dt_comp, "valor": valor,
                "cnpj_tomador": tomador["cnpj_cpf"], "cep_tomador": tomador["cep"],
                "cmun_tomador": cmun_tomador,
                "email_tomador": tomador.get("email", "").strip(),
                "logradouro": tomador["logradouro"][:80], "numero": tomador["numero"][:10],
                "bairro": tomador["bairro"][:60], "razao_social": tomador["razao_social"][:150],
                "servico": descricao, "item_lista": item_lista,
                "cnpj_prest": cnpj_prestador, "im_prest": im_p,
                "nDPS": num_v.lstrip('0') or "1",
                "iss_eh_retido": iss_eh_retido, "inss": v_inss,
                "aliq_iss": aliq_iss,
                "reg_ap_trib_sn": reg_ap_trib_sn,
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

                    # -------------------------------------------------------
                    # Registra no monitor para acompanhamento assíncrono.
                    # A thread de polling vai consultar o status a cada 15s
                    # e baixar o PDF quando a prefeitura processar a nota.
                    # -------------------------------------------------------
                    nome_prestador = self.prestador_nome_atual or cnpj_prestador
                    self.monitor.registrar_pendente(
                        protocolo=protocolo,
                        cnpj_prestador=cnpj_prestador,
                        nome_tomador=tomador["razao_social"],
                        nome_prestador=nome_prestador
                    )
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
                    <locPrest><cLocPrestacao>4208906</cLocPrestacao></locPrest>
                    <cServ>
                        <cTribNac>{d['item_lista']}</cTribNac>
                        <xDescServ>{d['servico']}</xDescServ>
                        <cNBS>101011200</cNBS>
                    </cServ>
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

    def trocar_certificado_logic(self):
        nome_p = self.combo_p.get()
        if not nome_p or nome_p == "Nenhum prestador cadastrado":
            return
        novo_pfx = filedialog.askopenfilename(title="Selecione o novo Certificado A1",
                                              filetypes=[("Certificado A1", "*.pfx")])
        if novo_pfx:
            nova_senha = simpledialog.askstring("Segurança", "Digite a senha do novo certificado:", show='*')
            if nova_senha:
                for p in self.db.listar_prestadores():
                    if p[0] == nome_p:
                        self.db.atualizar_certificado(p[1], novo_pfx, nova_senha)
                        self.parent.log_msg(f"Certificado da empresa {nome_p} atualizado.", "sucesso")
                        return

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
        ent_cnpj = criar_campo("CNPJ (Apenas números):", "Ex: 12345678000101")
        ent_im = criar_campo("Inscrição Municipal:", "Ex: 12345")
        ent_cnae = criar_campo("Código CNAE:", "Ex: 8211300")
        ent_servico = criar_campo("Código do Serviço (Municipal):", "Ex: 170201")
        ent_item = criar_campo("Item Lista Serviço (Nacional):", "Ex: 170201")

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
                "servico": ent_servico.get().strip(),
                "item": ent_item.get().strip(),
                "exigibilidade": ent_exig.get().split(" - ")[0],
                "natureza": ent_nat.get().split(" - ")[0],
                "iss_retido": ent_ret.get().split(" - ")[0],
                "aliquota": ent_aliq.get().strip(),
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