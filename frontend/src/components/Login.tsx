import { useMutation, useQuery } from "@tanstack/react-query";
import { Lock, RotateCw } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api, ApiError } from "@/lib/api";
import { Card } from "./ui";

/** Username, password and the security question (a new one on load, after every failed attempt and
 *  on request: each question works once). */
export function LoginForm({ onSignedIn }: { onSignedIn: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [answer, setAnswer] = useState("");
  const captcha = useQuery({ queryKey: ["admin-captcha"], queryFn: api.admin.captcha, staleTime: Infinity, refetchOnWindowFocus: false });
  const newQuestion = () => {
    setAnswer("");
    captcha.refetch();
  };
  const login = useMutation({
    mutationFn: () => api.admin.login(username, password, captcha.data?.token ?? "", answer.trim()),
    onSuccess: onSignedIn,
    onError: newQuestion,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };
  return (
    <form onSubmit={submit} className="space-y-3">
      <label className="block"><span className="label">Username</span><input className="input mt-1.5" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} /></label>
      <label className="block"><span className="label">Password</span><input className="input mt-1.5" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} autoFocus /></label>
      <label className="block">
        <span className="label">Security check</span>
        <div className="mt-1.5 flex items-center gap-2">
          <span className="num flex h-[38px] min-w-[7.5rem] select-none items-center justify-center rounded-lg border border-line bg-raised px-3 text-sm font-semibold tracking-wide" aria-live="polite">
            {captcha.data ? `${captcha.data.question} =` : captcha.isError ? "unavailable" : "…"}
          </span>
          <input className="input num" inputMode="numeric" autoComplete="off" placeholder="?" aria-label="Answer" maxLength={4}
            value={answer} onChange={(e) => setAnswer(e.target.value.replace(/[^0-9]/g, ""))} />
          <button type="button" className="btn shrink-0 px-2.5" onClick={newQuestion} title="New question" aria-label="New question">
            <RotateCw size={14} className={captcha.isFetching ? "animate-spin" : ""} />
          </button>
        </div>
      </label>
      {login.error && <p className="text-sm text-short">{(login.error as ApiError).message}</p>}
      <button className="btn btn-primary w-full" disabled={login.isPending || !password || !answer || !captcha.data}>{login.isPending ? "Signing in…" : "Sign in"}</button>
    </form>
  );
}

/** The only thing a visitor sees of a private site: no name, no data, no live connection. */
export function SignInScreen({ onSignedIn }: { onSignedIn: () => void }) {
  return (
    <main className="grid min-h-screen place-items-center bg-bg px-4 py-10">
      <div className="w-full max-w-sm">
        <Card className="card-pad">
          <div className="mb-5 flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-lg bg-accent/15 text-accent"><Lock size={18} /></div>
            <div>
              <h1 className="font-semibold">Private dashboard</h1>
              <p className="text-xs text-muted">Sign in to continue</p>
            </div>
          </div>
          <LoginForm onSignedIn={onSignedIn} />
        </Card>
      </div>
    </main>
  );
}
