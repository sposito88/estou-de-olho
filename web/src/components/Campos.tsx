import { useId } from "react";

interface Opcao {
  valor: string;
  rotulo: string;
}

interface CampoSelectProps {
  rotulo: string;
  valor: string;
  opcoes: Opcao[];
  onMudar: (valor: string) => void;
  /** Texto da opção vazia ("Todos"); `null` para não ter opção vazia. */
  todos?: string | null;
}

/** Select com rótulo visível e opção "Todos". */
export function CampoSelect({ rotulo, valor, opcoes, onMudar, todos = "Todos" }: CampoSelectProps) {
  const id = useId();
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="mb-1 block text-sm font-bold text-secondary">
        {rotulo}
      </label>
      <select id={id} className="input cursor-pointer" value={valor} onChange={(e) => onMudar(e.target.value)}>
        {todos !== null && <option value="">{todos}</option>}
        {opcoes.map((o) => (
          <option key={o.valor} value={o.valor}>
            {o.rotulo}
          </option>
        ))}
      </select>
    </div>
  );
}

export const opcoesSimples = (valores: (string | number)[]): Opcao[] =>
  valores.map((v) => ({ valor: String(v), rotulo: String(v) }));
