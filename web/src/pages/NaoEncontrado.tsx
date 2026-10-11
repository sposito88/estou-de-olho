import { Link } from "react-router";

export function NaoEncontrado({ mensagem = "Esta página não existe." }: { mensagem?: string }) {
  return (
    <div className="card mx-auto max-w-xl space-y-4 text-center">
      <h1 className="text-2xl font-bold text-primary">Não encontrado</h1>
      <p className="text-secondary">{mensagem}</p>
      <Link to="/" className="btn-primary">
        Voltar ao painel
      </Link>
    </div>
  );
}
