import os
import time
import json
import gzip
import base64
import threading
import tempfile
import requests
from datetime import datetime
from lxml import etree
from signxml import XMLSigner
from signxml.util import namespaces as _signxml_namespaces
from signxml.algorithms import SignatureMethod, DigestAlgorithm, CanonicalizationMethod
import customtkinter as ctk
import tkinter as tk
from tkinter import scrolledtext, filedialog
import pandas as pd

from certificado_utils import CertificadoA1
from betha_manual_modulo import EmissorBethaManual
from utils import isolar_scroll_mouse


class EmissorPortalNacional(EmissorBethaManual):
    """
    Emissão de NFS-e direto pela API oficial do Emissor Nacional (SEFIN Nacional),
    em vez do webservice proprietário da Betha. Motivo: a partir de 01/09/2026 a
    emissão em Jaraguá do Sul passa a ser obrigatória e exclusiva pelo Emissor
    Nacional (antecipável desde agosto/2026); o escritório também já atende
    empresas de outras cidades cuja emissão é feita pelo Portal Nacional.

    Reaproveita TODA a tela/cadastro/validação já existente em
    EmissorBethaManual (prestador, tomador, busca de CEP/CNPJ, cidade de
    prestação do serviço) — só substitui o transporte final
    (`_executar_transmissao_soap`) pelo envio oficial via mTLS ao SEFIN
    Nacional, e adiciona a cidade/ambiente de emissão (que deixou de ser um
    único município fixo, já que agora atendemos várias cidades).

    Endpoints confirmados em gov.br/nfse (.../apis-prod-restrita-e-producao):
      - ADN "Contribuinte" (a mesma API que nfse_api_modulo.py já usa para
        consulta) só tem 2 endpoints GET de consulta — não emite nada.
      - A emissão em si é no SEFIN Nacional: POST /nfse — "Recepciona a DPS
        e Gera a NFS-e de forma síncrona" (confirmado por relatos de
        implementadores; não achei o Swagger completo porque a doc do SEFIN
        exige certificado mTLS válido só para abrir a página).

    O único ponto não 100% confirmado é o path exato dentro do SEFIN Nacional
    e os nomes de campo do envelope JSON — por isso existe o botão
    "🔌 Testar Conexão", que faz uma chamada real com o certificado do
    usuário e mostra a resposta HTTP crua, para calibrar rapidamente caso o
    primeiro teste real aponte um ajuste necessário.
    """

    # URLs oficiais (confirmadas ao vivo em gov.br/nfse/pt-br/biblioteca/
    # documentacao-tecnica/apis-prod-restrita-e-producao — seção SEFIN NACIONAL)
    BASE_URL_SEFIN_RESTRITA = "https://sefin.producaorestrita.nfse.gov.br/API/SefinNacional"
    BASE_URL_SEFIN_PRODUCAO = "https://sefin.nfse.gov.br/SefinNacional"

    # Namespace/versão oficiais da DPS (padrão nacional, distinto do
    # namespace próprio "http://www.betha.com.br/e-nota-dps" que a Betha usa
    # internamente). Confirmado em 06/08/2026 contra Produção Restrita: a
    # v1.00 é rejeitada com "E1235: Falha no esquema XML do DF-e" (o
    # servidor já exige o leiaute v1.01, pós Reforma Tributária/IBS-CBS,
    # mesmo aceitando "1.00" como valor de atributo formalmente válido).
    DPS_NAMESPACE = "http://www.sped.fazenda.gov.br/nfse"
    DPS_VERSAO = "1.01"

    AMBIENTE_PADRAO = "Homologação"

    # Intervalo entre cada emissão no modo lote — evita rajadas contra a API
    # oficial (mesma preocupação de rate limit já tratada em nfse_api_modulo.py).
    DELAY_ENTRE_NOTAS_LOTE = 1.5

    def __init__(self, parent):
        super().__init__(parent)
        self.municipio_emissao_ibge = ""
        self.municipio_emissao_nome = ""
        self.municipio_emissao_uf = ""
        self.ambiente_emissao = self.AMBIENTE_PADRAO
        self._cert_temp_pn = None
        self._key_temp_pn = None
        self._parar_lote = False

    # ------------------------------------------------------------------
    # TELA DE ESCOLHA — espelha main.py: tela_escolha_emissor
    # ------------------------------------------------------------------
    def tela_escolha_emissor_pn(self):
        self.parent.limpar_tela()

        f_top = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_top.pack(pady=20)
        self.parent.carregar_logo(f_top)

        ctk.CTkLabel(self.parent.container, text="Emissor Portal Nacional — Selecione o Modo",
                     font=("Arial", 22, "bold"), text_color="#2980b9").pack(pady=10)

        f_btns = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_btns.pack(pady=40)

        ctk.CTkButton(f_btns, text="📊 EMISSÃO EM LOTE (EXCEL)",
                      command=self.tela_emissor_lote_pn,
                      width=400, height=80, font=("Arial", 18, "bold"),
                      fg_color="#1f538d", hover_color="#14375e").pack(pady=15)

        ctk.CTkButton(f_btns, text="✍️ EMISSÃO MANUAL (CADASTRO)",
                      command=self.tela_emissor_manual_pn,
                      width=400, height=80, font=("Arial", 18, "bold"),
                      fg_color="#2980b9", hover_color="#1f618d").pack(pady=15)

        ctk.CTkButton(f_btns, text="Voltar Menu Principal", command=self.parent.mostrar_menu_inicial,
                      width=400, height=80, fg_color="gray").pack(pady=30)

    # ------------------------------------------------------------------
    # TELA LOTE (EXCEL) — mesmas colunas de planilha já usadas no lote
    # Betha (betha_certificado_modulo.py), assim planilhas existentes
    # funcionam sem alteração. Reaproveita o motor já validado
    # (_executar_transmissao_soap) chamando-o linha a linha.
    # ------------------------------------------------------------------
    def tela_emissor_lote_pn(self):
        self.parent.limpar_tela()
        self._parar_lote = False

        f_top = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_top.pack(pady=10)
        self.parent.carregar_logo(f_top)

        ctk.CTkLabel(self.parent.container, text="📊 Emissão em Lote (Excel) — Portal Nacional",
                     font=("Arial", 20, "bold"), text_color="#2980b9").pack(pady=10)

        # --- PRESTADOR ---
        f_prest = ctk.CTkFrame(self.parent.container)
        f_prest.pack(fill="x", padx=40, pady=5)
        ctk.CTkLabel(f_prest, text="PRESTADOR (EMISSOR)", font=("Arial", 11, "bold"),
                     text_color="#1f538d").pack(pady=5)

        f_sel = ctk.CTkFrame(f_prest, fg_color="transparent")
        f_sel.pack(fill="x", padx=20, pady=3)

        lista_p = [p[0] for p in self.db.listar_prestadores()]
        if not lista_p:
            lista_p = ["Nenhum prestador cadastrado"]

        self.combo_p_lote = ctk.CTkComboBox(f_sel, values=lista_p, width=320,
                                            command=self._ao_selecionar_prestador_lote)
        self.combo_p_lote.pack(side="left", padx=5)

        ctk.CTkButton(f_sel, text="🌎 Cidade/Ambiente", width=160,
                      fg_color="#2980b9", hover_color="#1f618d",
                      command=self._janela_config_emissao_pn).pack(side="left", padx=10)

        self.lbl_municipio_lote = ctk.CTkLabel(f_sel, text="", font=("Arial", 11), anchor="w")
        self.lbl_municipio_lote.pack(side="left", padx=15)

        f_reg = ctk.CTkFrame(f_prest, fg_color="transparent")
        f_reg.pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkLabel(f_reg, text="Regime Esp. Tributação:", width=160, anchor="w",
                     font=("Arial", 11, "bold")).pack(side="left")
        self.combo_reg_esp_lote = ctk.CTkComboBox(f_reg, values=[
            "0 - Nenhum",
            "1 - Ato Cooperado (Cooperativa)",
            "2 - Estimativa",
            "3 - Microempresa Municipal",
            "4 - Notário ou Registrador",
            "5 - Profissional Autônomo",
            "6 - Sociedade de Profissionais",
            "9 - Outros",
        ], width=280, state="readonly")
        self.combo_reg_esp_lote.set("0 - Nenhum")
        self.combo_reg_esp_lote.pack(side="left", padx=10)
        ctk.CTkLabel(f_reg, text="⚠ Só '0' foi testado ao vivo até agora — outros valores podem "
                                  "revelar novas regras de negócio na primeira tentativa.",
                     font=("Arial", 10), text_color="#e67e22").pack(side="left", padx=5)

        # --- PLANILHA ---
        f_card = ctk.CTkFrame(self.parent.container)
        f_card.pack(fill="x", padx=40, pady=10)
        ctk.CTkLabel(f_card, text="Planilha Base (mesmas colunas do lote Betha):",
                     font=("Arial", 11, "bold")).pack(anchor="w", padx=20, pady=(10, 0))

        f_arq = ctk.CTkFrame(f_card, fg_color="transparent")
        f_arq.pack(fill="x", padx=20, pady=10)
        self.ent_excel_pn = ctk.CTkEntry(f_arq, width=500)
        self.ent_excel_pn.pack(side="left", padx=5)
        ctk.CTkButton(f_arq, text="Selecionar...", width=120,
                      command=self._selecionar_excel_pn).pack(side="left", padx=5)

        # --- LOG ---
        f_log = ctk.CTkFrame(self.parent.container)
        f_log.pack(fill="both", expand=True, padx=40, pady=10)
        ctk.CTkLabel(f_log, text="Log de Operação:", font=("Arial", 11, "bold"),
                     text_color="gray").pack(anchor="w", padx=15, pady=1)
        self.parent.txt_log = scrolledtext.ScrolledText(f_log, width=120, height=14, state='disabled',
                                                         bg="#1e1e1e", fg="white", font=("Consolas", 10))
        self.parent.txt_log.pack(padx=15, pady=5, fill="both", expand=True)
        isolar_scroll_mouse(self.parent.txt_log)

        # --- CONTROLES ---
        f_btns = ctk.CTkFrame(self.parent.container, fg_color="transparent")
        f_btns.pack(pady=10)
        ctk.CTkButton(f_btns, text="🚀 INICIAR EMISSÃO EM LOTE", command=self._iniciar_lote_pn,
                      width=280, height=50, font=("Arial", 14, "bold"),
                      fg_color="#27ae60", hover_color="#1e8449").pack(side="left", padx=10)
        ctk.CTkButton(f_btns, text="🛑 Parar", command=self._parar_lote_pn,
                      width=120, height=50, fg_color="#c0392b", hover_color="#962d22").pack(side="left", padx=10)
        ctk.CTkButton(f_btns, text="Voltar", command=self.tela_escolha_emissor_pn,
                      width=140, height=50, fg_color="gray").pack(side="left", padx=10)

        if lista_p and lista_p[0] != "Nenhum prestador cadastrado":
            self.combo_p_lote.set(lista_p[0])
            self._ao_selecionar_prestador_lote(lista_p[0])

    def _selecionar_excel_pn(self):
        caminho = filedialog.askopenfilename(
            title="Selecione a planilha de notas",
            filetypes=[("Excel", "*.xlsx *.xls"), ("Todos os arquivos", "*.*")]
        )
        if caminho:
            self.ent_excel_pn.delete(0, tk.END)
            self.ent_excel_pn.insert(0, caminho)

    def _parar_lote_pn(self):
        self._parar_lote = True
        self.parent.log_msg("Solicitação de parada recebida — encerra após a nota atual.", "erro")

    def _ao_selecionar_prestador_lote(self, nome_escolhido):
        """Versão enxuta de ao_selecionar_prestador — só carrega o estado
        necessário pro motor de emissão, sem tocar em widgets exclusivos
        da tela manual (que não existem aqui)."""
        if nome_escolhido == "Nenhum prestador cadastrado":
            return
        for p in self.db.listar_prestadores():
            if p[0] != nome_escolhido:
                continue
            p_dados = self.db.buscar_dados_prestador(p[1])
            if not p_dados:
                return
            self.prestador_id_atual = p_dados[0]
            self.prestador_cnpj_atual = str(p_dados[1]).strip()
            self.prestador_nome_atual = nome_escolhido
            self.municipio_emissao_ibge = str(p_dados[14]).strip() if len(p_dados) > 14 and p_dados[14] else ""
            self.municipio_emissao_nome = str(p_dados[15]).strip() if len(p_dados) > 15 and p_dados[15] else ""
            self.municipio_emissao_uf = str(p_dados[16]).strip() if len(p_dados) > 16 and p_dados[16] else ""
            self.ambiente_emissao = str(p_dados[17]).strip() if len(p_dados) > 17 and p_dados[17] else self.AMBIENTE_PADRAO
            break

        self._atualizar_label_municipio_emissao()

    def _iniciar_lote_pn(self):
        if not self.prestador_cnpj_atual:
            self.parent.log_msg("Selecione um prestador.", "erro")
            return
        if not self.municipio_emissao_ibge:
            self.parent.log_msg(
                "Esse prestador não tem cidade de emissão configurada — "
                "configure na Emissão Manual antes de rodar o lote.", "erro")
            return
        caminho = self.ent_excel_pn.get().strip()
        if not caminho or not os.path.exists(caminho):
            self.parent.log_msg("Selecione uma planilha Excel válida.", "erro")
            return

        reg_esp_trib = self.combo_reg_esp_lote.get().split(" - ")[0].strip()
        self._parar_lote = False
        threading.Thread(target=self._processar_lote_excel, args=(caminho, reg_esp_trib), daemon=True).start()

    def _processar_lote_excel(self, caminho_excel, reg_esp_trib):
        try:
            df = pd.read_excel(caminho_excel)
        except Exception as e:
            self.parent.log_msg(f"Erro ao ler planilha: {e}", "erro")
            return

        total = len(df)
        sucesso = 0
        falha = 0
        self.parent.log_msg(
            f"Iniciando emissão em lote — {total} nota(s) — prestador {self.prestador_nome_atual} "
            f"({self.ambiente_emissao})...", "info", divisor=True)

        for i, row in df.iterrows():
            if self._parar_lote:
                self.parent.log_msg("Lote interrompido pelo usuário.", "erro")
                break
            try:
                cnpj_tomador = "".join(filter(str.isdigit, str(row.get('Tomador - CPF/CNPJ', ''))))
                razao_social = str(row.get('Tomador - Nome/Razao Social', '')).strip().upper()
                tomador = {
                    "cnpj_cpf": cnpj_tomador,
                    "cep": "".join(filter(str.isdigit, str(row.get('Tomador - CEP', '')))),
                    "logradouro": str(row.get('Tomador - Endereco', '')).upper()[:80],
                    "numero": str(row.get('Tomador - Número', 'SN')).upper()[:10],
                    "bairro": str(row.get('Tomador - Bairro', '')).upper()[:60],
                    "razao_social": razao_social[:150],
                    "email": str(row.get('Tomador - Email', '')).strip().lower(),
                    "ultimo_cod_servico": str(row.get('Serviço - Código Serviço', '')).strip(),
                    "loc_prestacao_ibge": self.municipio_emissao_ibge,
                }
                valor = f"{float(str(row.get('Serviço - Valor Serviço', 0)).replace(',', '.')):.2f}"
                descricao = str(row.get('Serviço - Discriminação', '')).strip().upper()
                aliq_iss = f"{float(str(row.get('Serviço - Alíquota ISS', '2.00')).replace(',', '.')):.2f}"

                if not cnpj_tomador or not razao_social or not descricao:
                    self.parent.log_msg(f"[{i + 1}/{total}] Linha ignorada — CNPJ/Razão Social/Descrição em branco.", "erro")
                    falha += 1
                    continue

                self.parent.log_msg(f"[{i + 1}/{total}] Emitindo para {razao_social}...", "info")
                ok = self._executar_transmissao_soap(
                    self.prestador_cnpj_atual, tomador, valor, descricao,
                    False, "0.00", aliq_iss, "1", reg_esp_trib=reg_esp_trib, verbose=False
                )
                if ok:
                    sucesso += 1
                else:
                    falha += 1
            except Exception as e:
                falha += 1
                self.parent.log_msg(f"[{i + 1}/{total}] Erro ao processar linha: {e}", "erro")

            if i < total - 1 and not self._parar_lote:
                time.sleep(self.DELAY_ENTRE_NOTAS_LOTE)

        self.parent.log_msg(
            f"Lote concluído — {sucesso} nota(s) emitida(s), {falha} com erro/pulada(s).",
            "sucesso", divisor=True)

    # ------------------------------------------------------------------
    # TELA MANUAL — reaproveita EmissorBethaManual.tela_emissor_manual()
    # inteira e só injeta o painel de cidade/ambiente + ajusta textos.
    # ------------------------------------------------------------------
    def tela_emissor_manual_pn(self):
        super().tela_emissor_manual()
        self._injetar_painel_emissao_nacional()
        self._ajustar_textos_pn()
        self._atualizar_label_municipio_emissao()

    def _injetar_painel_emissao_nacional(self):
        f_pn = ctk.CTkFrame(self.parent.container, border_width=1, border_color="#2980b9")
        f_pn.pack(fill="x", padx=40, pady=5, before=self.f_toma)

        ctk.CTkLabel(f_pn, text="🏛️ EMISSÃO — PORTAL NACIONAL (SEFIN)", font=("Arial", 11, "bold"),
                     text_color="#2980b9").pack(pady=2)

        f_linha = ctk.CTkFrame(f_pn, fg_color="transparent")
        f_linha.pack(fill="x", padx=20, pady=3)

        self.lbl_municipio_emissao = ctk.CTkLabel(
            f_linha, text="Cidade de emissão: (não definida)", font=("Arial", 11), anchor="w")
        self.lbl_municipio_emissao.pack(side="left", padx=5)

        ctk.CTkButton(f_linha, text="🌎 Definir Cidade/Ambiente", width=190,
                      fg_color="#2980b9", hover_color="#1f618d",
                      command=self._janela_config_emissao_pn).pack(side="left", padx=10)

        ctk.CTkButton(f_linha, text="🔌 Testar Conexão", width=150,
                      fg_color="#8e44ad", hover_color="#6c3483",
                      command=self._testar_conexao).pack(side="left", padx=10)

    def _ajustar_textos_pn(self):
        """Repassa a tela herdada da Betha para renomear rótulos que ficariam
        enganosos aqui (ex.: 'Acompanhar Notas' aponta pro monitor SOAP da
        Betha, que não se aplica — essa API é síncrona)."""

        def walk(widget):
            for child in widget.winfo_children():
                try:
                    if isinstance(child, ctk.CTkButton):
                        texto = child.cget("text")
                        if texto == "🚀 EMITIR NFSE MANUAL":
                            child.configure(text="🚀 EMITIR VIA PORTAL NACIONAL")
                        elif texto == "📋 Acompanhar Notas":
                            child.configure(text="📜 Histórico de Emissões", command=self._tela_historico_pn)
                    elif isinstance(child, ctk.CTkLabel):
                        if child.cget("text") == "✍️ Emissão Manual & Cadastro Inteligente":
                            child.configure(text="🏛️ Emissão Manual — Portal Nacional", text_color="#2980b9")
                except Exception:
                    pass
                walk(child)

        walk(self.parent.container)

    def ao_selecionar_prestador(self, nome_escolhido):
        super().ao_selecionar_prestador(nome_escolhido)
        if nome_escolhido == "Nenhum prestador cadastrado" or not self.prestador_cnpj_atual:
            return
        p_dados = self.db.buscar_dados_prestador(self.prestador_cnpj_atual)
        if not p_dados:
            return
        self.municipio_emissao_ibge = str(p_dados[14]).strip() if len(p_dados) > 14 and p_dados[14] else ""
        self.municipio_emissao_nome = str(p_dados[15]).strip() if len(p_dados) > 15 and p_dados[15] else ""
        self.municipio_emissao_uf = str(p_dados[16]).strip() if len(p_dados) > 16 and p_dados[16] else ""
        self.ambiente_emissao = str(p_dados[17]).strip() if len(p_dados) > 17 and p_dados[17] else self.AMBIENTE_PADRAO
        self._atualizar_label_municipio_emissao()

    def _atualizar_label_municipio_emissao(self):
        # Atualiza o label da tela Manual (se ela estiver aberta) e o da
        # tela de Lote (se for essa a aberta) — a janela de configuração é
        # compartilhada pelas duas telas. `winfo_exists()` é necessário
        # porque o atributo continua no objeto mesmo depois que a tela
        # anterior foi destruída por limpar_tela() — sem essa checagem dá
        # TclError "invalid command name" ao trocar de tela.
        if hasattr(self, "lbl_municipio_emissao") and self.lbl_municipio_emissao.winfo_exists():
            if self.municipio_emissao_ibge:
                self.lbl_municipio_emissao.configure(
                    text=f"Cidade de emissão: {self.municipio_emissao_nome}-{self.municipio_emissao_uf} "
                         f"(IBGE {self.municipio_emissao_ibge}) | Ambiente: {self.ambiente_emissao}")
            else:
                self.lbl_municipio_emissao.configure(
                    text="⚠️ Cidade de emissão: (não definida — clique em 'Definir Cidade/Ambiente')")

        if hasattr(self, "lbl_municipio_lote") and self.lbl_municipio_lote.winfo_exists():
            if self.municipio_emissao_ibge:
                self.lbl_municipio_lote.configure(
                    text=f"Cidade de emissão: {self.municipio_emissao_nome}-{self.municipio_emissao_uf} "
                         f"| Ambiente: {self.ambiente_emissao}",
                    text_color="#27ae60")
            else:
                self.lbl_municipio_lote.configure(
                    text="⚠️ Sem cidade de emissão configurada.",
                    text_color="#e67e22")

    # ------------------------------------------------------------------
    # JANELA — definir cidade do emitente (cLocEmi) + ambiente, por prestador
    # ------------------------------------------------------------------
    def _janela_config_emissao_pn(self):
        if not self.prestador_cnpj_atual:
            self.parent.log_msg("Selecione um prestador antes de configurar a emissão nacional.", "erro")
            return

        janela = ctk.CTkToplevel(self.parent.root)
        janela.title("Cidade / Ambiente de Emissão — Portal Nacional")
        janela.geometry("480x600")
        janela.minsize(480, 600)
        janela.resizable(False, True)
        janela.transient(self.parent.root)
        janela.grab_set()
        janela.lift()
        janela.focus_force()

        ctk.CTkLabel(janela, text="Cidade do Emitente (cLocEmi)", font=("Arial", 13, "bold")).pack(pady=(15, 5))
        ent_busca = ctk.CTkEntry(janela, width=380, placeholder_text="Digite ao menos 3 letras da cidade...")
        ent_busca.pack(pady=5)
        if self.municipio_emissao_nome:
            ent_busca.insert(0, self.municipio_emissao_nome)

        lbl_sel = ctk.CTkLabel(
            janela,
            text=(f"Selecionada: {self.municipio_emissao_nome}-{self.municipio_emissao_uf} "
                  f"(IBGE {self.municipio_emissao_ibge})") if self.municipio_emissao_ibge
            else "Nenhuma cidade selecionada ainda.",
            font=("Arial", 11), text_color="#27ae60")
        lbl_sel.pack(pady=5)

        frame_lista = ctk.CTkScrollableFrame(janela, width=420, height=100)
        frame_lista.pack(pady=5)

        escolha = {
            "ibge": self.municipio_emissao_ibge,
            "nome": self.municipio_emissao_nome,
            "uf": self.municipio_emissao_uf,
        }

        def buscar(event=None):
            termo = ent_busca.get().strip()
            if len(termo) < 3:
                return
            threading.Thread(
                target=self._consultar_ibge_janela,
                args=(termo, frame_lista, escolha, lbl_sel, ent_busca),
                daemon=True
            ).start()

        ent_busca.bind("<KeyRelease>", buscar)

        ctk.CTkLabel(janela, text="Ambiente", font=("Arial", 13, "bold")).pack(pady=(15, 5))
        f_switch = ctk.CTkFrame(janela, fg_color="transparent")
        f_switch.pack(pady=5)
        var_amb_switch = ctk.BooleanVar(value=not self._eh_homologacao())
        ctk.CTkLabel(f_switch, text="Homologação", font=("Arial", 12)).pack(side="left", padx=(0, 10))
        switch_amb = ctk.CTkSwitch(f_switch, text="", variable=var_amb_switch,
                                   onvalue=True, offvalue=False, width=50)
        switch_amb.pack(side="left")
        ctk.CTkLabel(f_switch, text="Produção", font=("Arial", 12)).pack(side="left", padx=(10, 0))

        def salvar():
            if not escolha["ibge"]:
                self.parent.log_msg("Selecione uma cidade antes de salvar.", "erro")
                return
            self.municipio_emissao_ibge = escolha["ibge"]
            self.municipio_emissao_nome = escolha["nome"]
            self.municipio_emissao_uf = escolha["uf"]
            self.ambiente_emissao = "Produção" if var_amb_switch.get() else "Homologação"
            self.db.atualizar_municipio_emissao(
                self.prestador_cnpj_atual, self.municipio_emissao_ibge,
                self.municipio_emissao_nome, self.municipio_emissao_uf, self.ambiente_emissao)
            self._atualizar_label_municipio_emissao()
            self.parent.log_msg(
                f"Cidade de emissão definida: {self.municipio_emissao_nome}-{self.municipio_emissao_uf} "
                f"| Ambiente: {self.ambiente_emissao}", "sucesso")
            janela.destroy()

        ctk.CTkButton(janela, text="💾 Salvar", command=salvar, fg_color="#27ae60",
                      hover_color="#1e8449", width=200).pack(pady=15)

    def _consultar_ibge_janela(self, termo, frame_lista, escolha, lbl_sel, ent_busca):
        try:
            resp = requests.get("https://servicodados.ibge.gov.br/api/v1/localidades/municipios", timeout=8)
            if resp.status_code != 200:
                return
            cidades = resp.json()
            termo_lower = termo.lower()
            resultado = [c for c in cidades if termo_lower in c['nome'].lower()][:10]
            self.parent.root.after(
                0, lambda: self._exibir_dropdown_janela(resultado, frame_lista, escolha, lbl_sel, ent_busca))
        except Exception:
            pass

    def _exibir_dropdown_janela(self, cidades, frame_lista, escolha, lbl_sel, ent_busca):
        for w in frame_lista.winfo_children():
            w.destroy()
        for cidade in cidades:
            nome = cidade['nome']
            uf = cidade['microrregiao']['mesorregiao']['UF']['sigla']
            ibge = str(cidade['id'])

            def selecionar(n=nome, u=uf, i=ibge):
                escolha["ibge"], escolha["nome"], escolha["uf"] = i, n, u
                lbl_sel.configure(text=f"Selecionada: {n}-{u} (IBGE {i})")
                ent_busca.delete(0, tk.END)
                ent_busca.insert(0, n)
                for w in frame_lista.winfo_children():
                    w.destroy()

            ctk.CTkButton(frame_lista, text=f"{nome} - {uf}", anchor="w", fg_color="transparent",
                          hover_color="#3a3a3a", height=28, command=selecionar).pack(fill="x", pady=1)

    # ------------------------------------------------------------------
    # HISTÓRICO DE EMISSÕES (API é síncrona — não precisa de polling)
    # ------------------------------------------------------------------
    def _tela_historico_pn(self):
        janela = ctk.CTkToplevel(self.parent.root)
        janela.title("Histórico de Emissões — Portal Nacional")
        janela.geometry("900x520")
        janela.transient(self.parent.root)

        ctk.CTkLabel(janela, text="📜 Histórico de Emissões — Portal Nacional",
                     font=("Arial", 16, "bold"), text_color="#2980b9").pack(pady=10)

        frame = ctk.CTkScrollableFrame(janela, width=860, height=400)
        frame.pack(padx=15, pady=10, fill="both", expand=True)

        registros = self.db.listar_emissoes_pn()
        if not registros:
            ctk.CTkLabel(frame, text="Nenhuma emissão registrada ainda.", text_color="gray").pack(pady=20)
        else:
            for r in registros:
                (_id, dt, cnpj_p, nome_p, nome_t, amb, status,
                 num_nfse, chave, caminho_pdf, caminho_xml, erro) = r
                cor = "#27ae60" if status == "SUCESSO" else "#c0392b"
                linha = ctk.CTkFrame(frame, fg_color="transparent")
                linha.pack(fill="x", pady=2)
                texto = f"[{dt}] {status} — {nome_p} → {nome_t} | NFS-e {num_nfse or '-'} | {amb}"
                if status != "SUCESSO" and erro:
                    texto += f" | Erro: {erro[:120]}"
                ctk.CTkLabel(linha, text=texto, font=("Arial", 10), text_color=cor, anchor="w").pack(
                    side="left", fill="x", expand=True, padx=5)
                if caminho_pdf and os.path.exists(caminho_pdf):
                    ctk.CTkButton(linha, text="📄 Abrir PDF", width=100, height=24,
                                  command=lambda p=caminho_pdf: os.startfile(p)).pack(side="right", padx=5)

        ctk.CTkButton(janela, text="Fechar", command=janela.destroy, fg_color="gray", width=150).pack(pady=10)

    # ------------------------------------------------------------------
    # SESSÃO mTLS — mesmo padrão de nfse_api_modulo.py::_criar_sessao_mtls,
    # cópia própria (nomes _pn) para não colidir com a instância de
    # NFSeAPIModulo usada para consulta/download.
    # ------------------------------------------------------------------
    def _criar_sessao_mtls_pn(self, pfx_path, senha, cert_manager=None):
        """Se `cert_manager` já vier carregado (fluxo de emissão, que já
        abriu o certificado antes pra assinar a DPS), reaproveita em vez de
        reabrir o .pfx — evita reprocessar o PKCS12 e logar 'Cofre aberto'
        duas vezes por nota."""
        try:
            if cert_manager is None:
                cert_manager = CertificadoA1(pfx_path, senha)
                if not cert_manager.carregar_chaves(self.parent.log_msg):
                    return None

            cert_pem = cert_manager.obter_certificado_pem()
            key_pem = cert_manager.obter_chave_privada_pem()

            tf_cert = tempfile.NamedTemporaryFile(suffix="_cert.pem", delete=False, mode="wb")
            tf_cert.write(cert_pem.encode() if isinstance(cert_pem, str) else cert_pem)
            tf_cert.close()
            self._cert_temp_pn = tf_cert.name

            tf_key = tempfile.NamedTemporaryFile(suffix="_key.pem", delete=False, mode="wb")
            tf_key.write(key_pem.encode() if isinstance(key_pem, str) else key_pem)
            tf_key.close()
            self._key_temp_pn = tf_key.name

            sessao = requests.Session()
            sessao.cert = (self._cert_temp_pn, self._key_temp_pn)
            sessao.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
            return sessao
        except Exception as e:
            self.parent.log_msg(f"Erro ao criar sessão mTLS (Portal Nacional): {e}", "erro")
            return None

    def _limpar_temp_pn(self):
        for f in (self._cert_temp_pn, self._key_temp_pn):
            try:
                if f and os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass
        self._cert_temp_pn = None
        self._key_temp_pn = None

    def _eh_homologacao(self):
        # "Homologação" aparece tanto no rótulo curto novo ("Homologação")
        # quanto no texto antigo/legado salvo por versões anteriores desta
        # tela ("Produção Restrita (Homologação)") — cobre os dois sem
        # precisar migrar valores já salvos no banco.
        return "Homologação" in (self.ambiente_emissao or "") or "Restrita" in (self.ambiente_emissao or "")

    def _base_url_ativa(self):
        return self.BASE_URL_SEFIN_RESTRITA if self._eh_homologacao() else self.BASE_URL_SEFIN_PRODUCAO

    def _tp_amb_ativo(self):
        return "2" if self._eh_homologacao() else "1"

    # ------------------------------------------------------------------
    # 🔌 TESTAR CONEXÃO — chamada real (sem enviar DPS) só pra validar
    # handshake mTLS + roteamento antes de emitir de verdade.
    # ------------------------------------------------------------------
    def _testar_conexao(self):
        if not self.prestador_cnpj_atual:
            self.parent.log_msg("Selecione um prestador antes de testar a conexão.", "erro")
            return
        threading.Thread(target=self._testar_conexao_thread, daemon=True).start()

    def _testar_conexao_thread(self):
        try:
            p_dados = self.db.buscar_dados_prestador(self.prestador_cnpj_atual)
            if not p_dados:
                self.parent.log_msg("Prestador não encontrado no banco.", "erro")
                return
            caminho_pfx = str(p_dados[4]).strip()
            senha_pfx = str(p_dados[5]).strip()
            base_url = self._base_url_ativa()

            self.parent.log_msg(f"🔌 Testando conexão mTLS com {base_url} ({self.ambiente_emissao})...", "info")
            sessao = self._criar_sessao_mtls_pn(caminho_pfx, senha_pfx)
            if sessao is None:
                return
            try:
                # Chamada de leitura mínima, só pra validar o handshake mTLS
                # e o roteamento do host — não emite nenhuma DPS real.
                resp = sessao.get(f"{base_url}/nfse/1", timeout=20)
                self.parent.log_msg(
                    f"🔌 Resposta do servidor: HTTP {resp.status_code} — corpo: {resp.text[:400]}", "info")
            except requests.exceptions.SSLError as e:
                self.parent.log_msg(f"🔌 Erro de TLS/certificado: {e}", "erro")
            except Exception as e:
                self.parent.log_msg(f"🔌 Erro de conexão: {e}", "erro")
            finally:
                self._limpar_temp_pn()
        except Exception as e:
            self.parent.log_msg(f"Erro no teste de conexão: {e}", "erro")

    # ------------------------------------------------------------------
    # TRANSPORTE — substitui EmissorBethaManual._executar_transmissao_soap.
    # Mesma assinatura: é chamado automaticamente pelo fluxo_emissao_manual
    # herdado (validação de campos, salvar tomador etc. tudo reaproveitado).
    # ------------------------------------------------------------------
    def _executar_transmissao_soap(self, cnpj_prestador, tomador, valor, descricao,
                                   iss_eh_retido, v_inss, aliq_iss, reg_ap_trib_sn,
                                   reg_esp_trib="0", verbose=True):
        """`verbose=False` (usado no lote) suprime as linhas intermediárias
        de diagnóstico e deixa só 'Emitindo para X...' + o resultado final,
        igual ao padrão enxuto que a Betha já usava no lote."""
        if not self.municipio_emissao_ibge:
            self.parent.log_msg(
                "Erro: defina a Cidade de Emissão (Portal Nacional) antes de emitir — "
                "clique em '🌎 Definir Cidade/Ambiente' no topo da tela.", "erro")
            return False

        cep_limpo = tomador["cep"].replace("-", "").strip()
        cmun_tomador = "0000000"
        try:
            resp_cep = requests.get(f"https://viacep.com.br/ws/{cep_limpo}/json/", timeout=5)
            if resp_cep.status_code == 200:
                cmun_tomador = resp_cep.json().get("ibge", "0000000")
        except Exception:
            self.parent.log_msg(
                "Aviso: não foi possível consultar o CEP do tomador. Usando código IBGE genérico.", "erro")

        base_url = self._base_url_ativa()
        tp_amb = self._tp_amb_ativo()
        nome_prestador = self.prestador_nome_atual or cnpj_prestador

        registro = {
            "dt_emissao": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "prestador_cnpj": cnpj_prestador,
            "prestador_nome": nome_prestador,
            "tomador_nome": tomador.get("razao_social", ""),
            "ambiente": self.ambiente_emissao,
        }

        try:
            p_dados = self.db.buscar_dados_prestador(cnpj_prestador)
            im_p = str(p_dados[2]).strip()
            caminho_pfx = str(p_dados[4]).strip()
            senha_pfx = str(p_dados[5]).strip()
            nbs = str(p_dados[13]).strip() if len(p_dados) > 13 and p_dados[13] else "101011200"

            item_lista = tomador.get("ultimo_cod_servico", "").replace('.', '').ljust(6, '0') \
                         or str(p_dados[8]).replace('.', '').ljust(6, '0')

            if verbose:
                self.parent.log_msg("Abrindo cofre de segurança... Inicializando Certificado Digital A1.", "info")
            cert_manager = CertificadoA1(caminho_pfx, senha_pfx)
            # "Cofre aberto com sucesso!" é logado de dentro do
            # certificado_utils.py (arquivo compartilhado) — só passa a
            # função de log quando verbose, senão essa linha sempre aparece
            # mesmo no modo enxuto do lote.
            if not cert_manager.carregar_chaves(self.parent.log_msg if verbose else None):
                if not verbose:
                    self.parent.log_msg("Erro: falha ao abrir o certificado digital do prestador.", "erro")
                return False
        except Exception as e:
            self.parent.log_msg(f"Erro Crítico ao carregar dados do prestador/certificado: {e}", "erro")
            registro.update(status="ERRO", mensagem_erro=str(e))
            self.db.registrar_emissao_pn(registro)
            return False

        try:
            tempo_seguro = time.time() - 300
            dh_emi = time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(tempo_seguro)) + "-03:00"
            dt_comp = time.strftime('%Y-%m-%d', time.localtime(tempo_seguro))

            num_v = str(int(time.time() * 1000) % 1000000000000000).zfill(15)
            cloc_emi = self.municipio_emissao_ibge.zfill(7)
            id_45 = f"DPS{cloc_emi}2{cnpj_prestador.zfill(14)}{'900'.zfill(5)}{num_v}"

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
                "iss_eh_retido": iss_eh_retido, "inss": v_inss, "aliq_iss": aliq_iss,
                "reg_ap_trib_sn": reg_ap_trib_sn,
                "reg_esp_trib": reg_esp_trib,
                "cLocEmi": cloc_emi,
                "loc_prestacao_ibge": tomador.get("loc_prestacao_ibge") or cloc_emi,
                "nbs": nbs,
            }

            if verbose:
                self.parent.log_msg(f"Montando e assinando DPS nacional número {dados_xml['nDPS']}...", "info")
            xml_corpo = self._gerar_xml_dps_nacional(dados_xml, tp_amb)

            root = etree.fromstring(xml_corpo.encode('utf-8'))
            signer = XMLSigner()
            # O validador do SEFIN Nacional rejeita prefixo de namespace no
            # bloco de assinatura (confirmado ao vivo: erro E1228 "Xml
            # declarado com prefixo de namespace" com o <ds:Signature>
            # padrão do signxml). Troca pra namespace default sem prefixo:
            # <Signature xmlns="http://www.w3.org/2000/09/xmldsig#">.
            signer.namespaces = {None: _signxml_namespaces.ds}
            # O XSD oficial (xmldsig-core-schema_v1.00.xsd, bundle SEFIN)
            # fixa os algoritmos clássicos — SHA1 + Canonical XML 1.0 — em
            # vez dos padrões modernos do signxml (SHA256 + C14N 1.1),
            # confirmado validando localmente contra o schema baixado de
            # gov.br/nfse. Setar depois do __init__ pula a checagem
            # anti-SHA1 do signxml (ela só roda uma vez, na construção).
            signer.sign_alg = SignatureMethod.RSA_SHA1
            signer.digest_alg = DigestAlgorithm.SHA1
            signer.c14n_alg = CanonicalizationMethod.CANONICAL_XML_1_0
            signed_root = signer.sign(root, key=cert_manager.obter_chave_privada_pem(),
                                      cert=cert_manager.obter_certificado_pem(),
                                      reference_uri=f"#{dados_xml['id_45']}")
            # IMPORTANTE: ao contrário do envio pra Betha (que embrulha a DPS
            # dentro de um envelope SOAP e por isso descarta a declaração),
            # o SEFIN Nacional recebe o XML da DPS puro dentro do gzip — e
            # exige a declaração <?xml version="1.0" encoding="UTF-8"?>
            # explícita (confirmado ao vivo: erro E1229 "Xml não está
            # utilizando codificação UTF-8" quando ela vem sem essa linha).
            xml_assinado = etree.tostring(signed_root, encoding='UTF-8', xml_declaration=True)

            # Log de depuração — salva o XML assinado exatamente como foi
            # enviado, pra dar pra inspecionar/validar offline caso o SEFIN
            # rejeite. Fica em NFSe_PDFs/PORTAL_NACIONAL/_debug_dps/.
            try:
                pasta_debug = os.path.join(
                    self.parent.configuracoes.get(
                        "pasta_pdfs", os.path.join(self.parent.pasta_exe, "NFSe_PDFs")),
                    "PORTAL_NACIONAL", "_debug_dps")
                os.makedirs(pasta_debug, exist_ok=True)
                caminho_debug = os.path.join(pasta_debug, f"DPS_{dados_xml['nDPS']}.xml")
                with open(caminho_debug, "wb") as f:
                    f.write(xml_assinado)
                if verbose:
                    self.parent.log_msg(f"🐞 XML assinado salvo para depuração: {caminho_debug}", "info")
            except Exception:
                pass
        except Exception as e:
            self.parent.log_msg(f"Erro ao montar/assinar a DPS: {e}", "erro")
            registro.update(status="ERRO", mensagem_erro=str(e))
            self.db.registrar_emissao_pn(registro)
            return False

        sessao = None
        try:
            payload_b64 = base64.b64encode(gzip.compress(xml_assinado)).decode("ascii")
            sessao = self._criar_sessao_mtls_pn(caminho_pfx, senha_pfx, cert_manager=cert_manager)
            if sessao is None:
                registro.update(status="ERRO", mensagem_erro="Falha ao montar sessão mTLS")
                self.db.registrar_emissao_pn(registro)
                return False

            if verbose:
                self.parent.log_msg(f"Transmitindo DPS ao SEFIN Nacional ({self.ambiente_emissao})...", "info")
            resp = sessao.post(f"{base_url}/nfse", json={"dpsXmlGZipB64": payload_b64}, timeout=60)
            return self._processar_resposta_sefin(resp, xml_assinado, registro, verbose=verbose)
        except Exception as e:
            self.parent.log_msg(f"Erro Crítico de transmissão ao SEFIN Nacional: {e}", "erro")
            registro.update(status="ERRO", mensagem_erro=str(e))
            self.db.registrar_emissao_pn(registro)
            return False
        finally:
            self._limpar_temp_pn()

    def _processar_resposta_sefin(self, resp, xml_dps_assinado, registro, verbose=True):
        if resp.status_code in (200, 201):
            try:
                corpo = resp.json()
            except Exception:
                corpo = {}

            nfse_b64_gzip = corpo.get("nfseXmlGZipB64") or corpo.get("NfseXmlGZipB64")
            if nfse_b64_gzip:
                xml_nfse = gzip.decompress(base64.b64decode(nfse_b64_gzip))
            else:
                # Ainda não confirmamos o nome exato do campo de resposta —
                # usa a própria DPS assinada como fallback (o DANFSe sai com
                # dados parciais, sem chave/nNFSe oficiais, até ajustarmos
                # isso com base numa resposta real).
                xml_nfse = xml_dps_assinado

            chave = corpo.get("chaveAcesso") or corpo.get("ChaveAcesso") or ""
            self.parent.estatisticas.registrar_evento("nota_emitida")

            pasta_pdfs = self.parent.configuracoes.get(
                "pasta_pdfs", os.path.join(self.parent.pasta_exe, "NFSe_PDFs"))
            nome_base = f"NFSE_PN_{registro['prestador_nome'][:20]}_{int(time.time())}" \
                .replace(" ", "_").replace("/", "-")
            pasta_dest = os.path.join(pasta_pdfs, "PORTAL_NACIONAL")
            os.makedirs(pasta_dest, exist_ok=True)

            caminho_xml = os.path.join(pasta_dest, f"{nome_base}.xml")
            with open(caminho_xml, "wb") as f:
                f.write(xml_nfse)

            dados_pdf = None
            try:
                dados_pdf = self.parent.nfse.nfse_api._gerar_pdf_e_extrair_dados(
                    xml_nfse, pasta_dest, nome_base)
            except Exception as e:
                self.parent.log_msg(f"Aviso: NFS-e emitida, mas falhou ao gerar o PDF do DANFSe: {e}", "erro")

            numero_nfse = (dados_pdf or {}).get("NFS-e", "")
            self.parent.log_msg(
                f"✅ SUCESSO! NFS-e nº {numero_nfse or '?'} — Chave: {chave or '(ver XML)'}", "sucesso")

            caminho_pdf = os.path.join(pasta_dest, f"{nome_base}.pdf") if dados_pdf else ""
            registro.update(
                status="SUCESSO",
                numero_nfse=numero_nfse,
                chave_acesso=chave or (dados_pdf or {}).get("Chave", ""),
                caminho_pdf=caminho_pdf, caminho_xml=caminho_xml,
            )
            self.db.registrar_emissao_pn(registro)
            return True
        else:
            motivo = self._extrair_erro_sefin(resp)
            self.parent.log_msg(f"REJEITADA PELO SEFIN NACIONAL (HTTP {resp.status_code}): {motivo}", "erro")
            registro.update(status="ERRO", mensagem_erro=f"HTTP {resp.status_code}: {motivo}")
            self.db.registrar_emissao_pn(registro)
            return False

    def _extrair_erro_sefin(self, resp):
        """
        Formato confirmado ao vivo em 06/08/2026 contra
        sefin.producaorestrita.nfse.gov.br (SefinNacional_1.6.0):
            {"tipoAmbiente": 2, "versaoAplicativo": "...",
             "dataHoraProcessamento": "...",
             "erro": {"codigo": "E2406", "descricao": "..."}}
        Mantém os formatos antigos (Erros/erros em lista) como fallback,
        caso o POST /nfse devolva uma estrutura diferente do GET testado.
        """
        try:
            corpo = resp.json()
            if isinstance(corpo, dict):
                erro_unico = corpo.get("erro") or corpo.get("Erro")
                if isinstance(erro_unico, dict):
                    cod = erro_unico.get("codigo", erro_unico.get("Codigo", ""))
                    desc = erro_unico.get("descricao", erro_unico.get("Descricao", ""))
                    return f"{cod}: {desc}"

                erros = corpo.get("Erros") or corpo.get("erros") or []
                if erros:
                    partes = []
                    for e in erros:
                        if isinstance(e, dict):
                            cod = e.get("Codigo", e.get("codigo", ""))
                            desc = e.get("Descricao", e.get("descricao", e))
                            partes.append(f"{cod}: {desc}")
                        else:
                            partes.append(str(e))
                    return "; ".join(partes)
                return json.dumps(corpo, ensure_ascii=False)[:500]
        except Exception:
            pass
        return (resp.text or "")[:500]

    # ------------------------------------------------------------------
    # DPS oficial (padrão nacional) — mesmo conteúdo fiscal que
    # betha_certificado_modulo.py::_gerar_xml_dps_corpo, mas com o
    # namespace/versão oficiais e cLocEmi dinâmico por prestador (em vez
    # de fixo em Jaraguá do Sul).
    #
    # NOTA: <IM> (Inscrição Municipal) do prestador foi deliberadamente
    # omitida — é opcional no schema (minOccurs=0), e o SEFIN Nacional
    # rejeitou com "E0120: IM do prestador não deve ser informado, pois
    # não existem informações complementares registradas no CNC NFS-e do
    # município emissor" quando ela vinha preenchida (confirmado ao vivo
    # em Produção Restrita, 06/08/2026). Se algum município específico
    # passar a exigi-la de volta, isso precisa virar condicional por
    # cLocEmi em vez de omissão fixa.
    # ------------------------------------------------------------------
    @staticmethod
    def _escapar_xml(texto) -> str:
        """Escapa caracteres especiais (&, <, >, aspas) pra não quebrar o
        XML — confirmado ao vivo: um '&' cru na Razão Social ("PRATICA &
        CONTABILIDADE LTDA") causava 'xmlParseEntityRef: no name' na hora
        de assinar. Mesmo padrão de betha_certificado_modulo.py::_sanitizar_xml."""
        if not texto:
            return ""
        return (str(texto)
                .replace("&", "&amp;")  # DEVE ser o primeiro sempre
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&apos;"))

    def _gerar_xml_dps_nacional(self, d, tp_amb):
        # Escapa todos os campos de texto livre vindos do cadastro/planilha
        # antes de montar o XML — nomes, endereços e descrição de serviço
        # podem conter '&', '<', '>' digitados por qualquer usuário.
        for campo in ('razao_social', 'servico', 'logradouro', 'bairro', 'email_tomador'):
            if campo in d:
                d[campo] = self._escapar_xml(d[campo])

        bloco_inss = (
            f"<tribFed><vRetCP>{d['inss']}</vRetCP></tribFed>"
            if float(d['inss']) > 0 else ""
        )
        valor_tp_ret_issqn = "2" if d['iss_eh_retido'] else "1"
        # E0625 (confirmado ao vivo, 06/08/2026): não é permitido informar
        # <pAliq> quando o ISS não é retido (tpRetISSQN=1) e a apuração é
        # pelo próprio Simples Nacional (regApTribSN=1) — nesse caso o
        # sistema já embute o ISS no DAS, então a alíquota some do XML.
        bloco_paliq = (
            "" if (valor_tp_ret_issqn == "1" and str(d['reg_ap_trib_sn']) == "1")
            else f"<pAliq>{d['aliq_iss']}</pAliq>"
        )
        doc_tomador = (
            f"<CPF>{d['cnpj_tomador']}</CPF>" if len(d['cnpj_tomador']) == 11
            else f"<CNPJ>{d['cnpj_tomador']}</CNPJ>"
        )
        bloco_email_tomador = f"<email>{d['email_tomador']}</email>" if d.get('email_tomador') else ""

        return f"""<DPS xmlns="{self.DPS_NAMESPACE}" versao="{self.DPS_VERSAO}">
            <infDPS Id="{d['id_45']}">
                <tpAmb>{tp_amb}</tpAmb>
                <dhEmi>{d['dhEmi']}</dhEmi>
                <verAplic>AbentrothPN_v1.0</verAplic>
                <serie>900</serie>
                <nDPS>{d['nDPS']}</nDPS>
                <dCompet>{d['dCompet']}</dCompet>
                <tpEmit>1</tpEmit>
                <cLocEmi>{d['cLocEmi']}</cLocEmi>
                <prest>
                    <CNPJ>{d['cnpj_prest']}</CNPJ>
                    <regTrib>
                        <opSimpNac>3</opSimpNac>
                        <regApTribSN>{d['reg_ap_trib_sn']}</regApTribSN>
                        <regEspTrib>{d.get('reg_esp_trib', '0')}</regEspTrib>
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
                </serv>
                <valores>
                    <vServPrest><vServ>{d['valor']}</vServ></vServPrest>
                    <trib>
                        <tribMun>
                            <tribISSQN>1</tribISSQN>
                            <tpRetISSQN>{valor_tp_ret_issqn}</tpRetISSQN>
                            {bloco_paliq}
                        </tribMun>
                        {bloco_inss}
                        <totTrib>
                            <pTotTribSN>{d['aliq_iss']}</pTotTribSN>
                        </totTrib>
                    </trib>
                </valores>
            </infDPS>
        </DPS>"""
