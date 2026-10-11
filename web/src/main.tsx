import { StrictMode, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import "./index.css";
import { MUNICIPIO_PADRAO } from "./lib/config";
import { NaoEncontrado } from "./pages/NaoEncontrado";
import { Painel } from "./pages/Painel";

// Páginas com gráfico (Recharts) ficam em pacotes separados.
const Cidade = lazy(() => import("./pages/Cidade").then((m) => ({ default: m.Cidade })));
const Deputado = lazy(() => import("./pages/Deputado").then((m) => ({ default: m.Deputado })));
const Deputados = lazy(() => import("./pages/Deputados").then((m) => ({ default: m.Deputados })));
const Sobre = lazy(() => import("./pages/Sobre").then((m) => ({ default: m.Sobre })));
const Alertas = lazy(() => import("./pages/Alertas").then((m) => ({ default: m.Alertas })));
const Fornecedor = lazy(() => import("./pages/Fornecedor").then((m) => ({ default: m.Fornecedor })));
const Estaduais = lazy(() => import("./pages/Estaduais").then((m) => ({ default: m.Estaduais })));
const Estadual = lazy(() => import("./pages/Estadual").then((m) => ({ default: m.Estadual })));
const Camara = lazy(() => import("./pages/Camara").then((m) => ({ default: m.Camara })));
const Prefeitura = lazy(() => import("./pages/Prefeitura").then((m) => ({ default: m.Prefeitura })));
const Contratos = lazy(() => import("./pages/Contratos").then((m) => ({ default: m.Contratos })));
const DadosAbertos = lazy(() => import("./pages/DadosAbertos").then((m) => ({ default: m.DadosAbertos })));
const Contestar = lazy(() => import("./pages/Contestar").then((m) => ({ default: m.Contestar })));
const Correcoes = lazy(() => import("./pages/Correcoes").then((m) => ({ default: m.Correcoes })));
const Privacidade = lazy(() => import("./pages/Privacidade").then((m) => ({ default: m.Privacidade })));
const Busca = lazy(() => import("./pages/Busca").then((m) => ({ default: m.Busca })));
const Pessoal = lazy(() => import("./pages/Pessoal").then((m) => ({ default: m.Pessoal })));
const EmendaPix = lazy(() => import("./pages/EmendaPix").then((m) => ({ default: m.EmendaPix })));
const Contas = lazy(() => import("./pages/Contas").then((m) => ({ default: m.Contas })));
const Eleitos = lazy(() => import("./pages/Eleitos").then((m) => ({ default: m.Eleitos })));
const Senadores = lazy(() => import("./pages/Senadores").then((m) => ({ default: m.Senadores })));
const Senador = lazy(() => import("./pages/Senador").then((m) => ({ default: m.Senador })));

const cidadePadrao = `/cidade/${MUNICIPIO_PADRAO.uf}/${encodeURIComponent(MUNICIPIO_PADRAO.nome)}`;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Painel />} />
          <Route path="deputados" element={<Deputados />} />
          <Route path="deputados/:id" element={<Deputado />} />
          <Route path="cidade" element={<Navigate to={cidadePadrao} replace />} />
          <Route path="cidade/:uf/:municipio" element={<Cidade />} />
          <Route path="cidade/:uf/:municipio/contratos" element={<Contratos />} />
          <Route path="cidade/:uf/:municipio/emenda-pix" element={<EmendaPix />} />
          <Route path="cidade/:uf/:municipio/contas" element={<Contas />} />
          <Route path="cidade/:uf/:municipio/eleitos" element={<Eleitos />} />
          <Route path="cidade/:uf/:municipio/camara" element={<Camara />} />
          <Route path="cidade/:uf/:municipio/prefeitura" element={<Prefeitura />} />
          <Route path="cidade/:uf/:municipio/pessoal" element={<Pessoal />} />
          <Route path="cidade/:uf/:municipio/busca" element={<Busca />} />
          <Route path="senadores" element={<Senadores />} />
          <Route path="senadores/:id" element={<Senador />} />
          <Route path="estaduais" element={<Estaduais />} />
          <Route path="estaduais/:id" element={<Estadual />} />
          <Route path="alertas" element={<Alertas />} />
          <Route path="fornecedores/:cnpj" element={<Fornecedor />} />
          <Route path="busca" element={<Busca />} />
          <Route path="contestar" element={<Contestar />} />
          <Route path="dados-abertos" element={<DadosAbertos />} />
          <Route path="correcoes" element={<Correcoes />} />
          <Route path="privacidade" element={<Privacidade />} />
          <Route path="sobre" element={<Sobre />} />
          <Route path="*" element={<NaoEncontrado />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
);
