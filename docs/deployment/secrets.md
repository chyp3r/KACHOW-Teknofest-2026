# Sır Yönetimi

## Docker Compose

`.env.prod` — `cp .env.prod.example .env.prod`, sonra her satırı gerçek
bir değerle doldurun. `.env.prod` `.gitignore`'da olmalı (kontrol edin);
`compose.prod.yml`'in `${VAR:?mesaj}` söz dizimi, boş bırakılan zorunlu
bir değişkende `up`'ı reddeder — sessiz bir güvensiz varsayılana düşme
riski yok.

## Kubernetes

`deploy/kubernetes/secrets.yaml`, üç desteklenen yoldan **birini**
belgelemek için var, kendisi güvenli bir dağıtım mekanizması değil (kendi
üst yorumunda açıkça yazıyor: placeholder değerlerle commit'li bir
`Secret` manifesti, gerçek bir değerin sonradan yapıştırılıp alışkanlıkla
commit'lenmesine davetiye çıkarır).

### 1. `kubectl create secret` (en basit, küçük deployment'lar için)

```bash
kubectl create secret generic kachow-secrets -n kachow \
  --from-literal=SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=POSTGRES_USER=postgres \
  --from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 24)" \
  --from-literal=KACHOW_APP_DB_PASSWORD="$(openssl rand -hex 24)" \
  --from-literal=LANGFUSE_PUBLIC_KEY= \
  --from-literal=LANGFUSE_SECRET_KEY= \
  --from-literal=S3_ACCESS_KEY= \
  --from-literal=S3_SECRET_KEY=
```

Hiçbir zaman commit edilmez; kim çalıştırdıysa kendi shell geçmişinde/
password manager'ında saklar.

### 2. Sealed Secrets (bitnami-labs/sealed-secrets)

Cluster'ın public anahtarıyla şifreleyin, **şifreli** `SealedSecret`'ı
commit edin (`kachow-secrets.yaml` yerine `kachow-sealedsecret.yaml`
gibi bir isimle, `deploy/kubernetes/secrets.yaml`'ı silin/gitignore'a
alın):

```bash
kubeseal --format yaml < my-real-secret.yaml > sealed-secret.yaml
```

### 3. External Secrets Operator (ESO) — büyüyen deployment'lar için

`deploy/kubernetes/secrets.yaml`'ın alt kısmındaki (yorumlu)
`ExternalSecret` örneğini kullanın. ESO kurulu ve bir `ClusterSecretStore`
(Vault, AWS Secrets Manager, GCP Secret Manager) yapılandırılmış olmalı.
Bu yol gerçek sırrı hiçbir zaman git geçmişine sokmaz ve rotasyonu
otomatikleştirir (`refreshInterval`).

## Rotasyon

`SECRET_KEY` rotasyonu her aktif JWT'yi geçersiz kılar (herkes yeniden
login olur) — planlı bir bakım penceresinde yapın.
`KACHOW_APP_DB_PASSWORD`/`POSTGRES_PASSWORD` rotasyonu Postgres'te
`ALTER ROLE ... PASSWORD` + Secret güncellemesi + `backend`/`migrate`
pod'larının yeniden başlatılmasını gerektirir (env değişkenleri bir pod
zaten çalışırken değişmez).

## Ne asla commit edilmemeli

- Gerçek değerlerle doldurulmuş `.env.prod` (compose).
- Gerçek değerlerle doldurulmuş `deploy/kubernetes/secrets.yaml` (k8s,
  Sealed Secrets'a geçmediyseniz).
- `SECRET_KEY`, herhangi bir `*_PASSWORD`, `S3_SECRET_KEY`,
  `LANGFUSE_SECRET_KEY`.
