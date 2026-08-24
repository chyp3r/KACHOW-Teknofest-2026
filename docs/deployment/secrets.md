# Sır (Secret) Yönetimi

> Kimlik bilgileri, API anahtarları ve şifrelerin güvenli yönetimi için rehberdir. Ortama göre sır yönetimi farklılık gösterir.

---

## Docker Compose

`.env.prod` dosyası temel sır depolama noktasıdır. 
Kullanımı: `cp .env.prod.example .env.prod`
- Dosyadaki her satır gerçek değerlerle doldurulmalıdır.
- `compose.prod.yml` dosyasındaki `${VAR:?mesaj}` notasyonu sayesinde, boş bırakılan zorunlu değişkenler (Örn: veritabanı şifreleri) konteynerlerin başlatılmasını durdurur (Fail-Fast).
- `.env.prod` dosyasının versiyon kontrolde (`.gitignore`) hariç tutulduğundan emin olun.

---

## Kubernetes

`deploy/kubernetes/secrets.yaml` dosyası yalnızca örnek yapıları (Placeholder) gösterir, gerçek şifreleri içine yazıp commit etmek güvenlik ihlalidir. Kubernetes'te 3 farklı strateji desteklenir:

### 1. `kubectl create secret` (Basit ve Küçük Kurulumlar İçin)

CLI üzerinden şifreleri dinamik üreterek (OpenSSL) kümeye (Cluster) tanımlayabilirsiniz. Git geçmişine girmez.

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

### 2. Sealed Secrets (Orta Ölçekli, GitOps)

Cluster'ın public anahtarıyla şifrelenmiş YAML (SealedSecret) dosyası commit edilebilir.

```bash
kubeseal --format yaml < my-real-secret.yaml > sealed-secret.yaml
```

### 3. External Secrets Operator (Büyük Kurulumlar, Vault/AWS entegre)

Kurumsal ortamlarda `ClusterSecretStore` (Örn: HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager) kullanılır. 
Sırlar otomatik olarak çekilir ve rotasyon `refreshInterval` ile sağlanır. `deploy/kubernetes/secrets.yaml` içerisindeki örnek ES konfigürasyonunu inceleyiniz.

---

## Rotasyon (Şifre Değişimi)

- **`SECRET_KEY` Rotasyonu:** Aktif tüm JWT (Kullanıcı oturumları) anahtarlarını geçersiz kılar. Planlı bakım aralığında (Maintenance Window) yapılmalıdır.
- **Veritabanı Şifre Rotasyonu:** Pod/Deployment tarafındaki Secret güncellemesinin yanı sıra, Postgres içinde de `ALTER ROLE ... PASSWORD` çalıştırılmalıdır. Sonrasında Backend pod'ları yeniden başlatılmalıdır.

---

## Kesinlikle Commit Edilmeyecekler!

Aşağıdaki verilerin `git push` ile repoya gitmesi yasaktır:
- İçi doldurulmuş `.env.prod` dosyası.
- İçi doldurulmuş k8s `secrets.yaml` dosyası (Sealed Secrets formatında değilse).
- `SECRET_KEY`, `POSTGRES_PASSWORD`, `S3_SECRET_KEY`, `LANGFUSE_SECRET_KEY` gibi anahtarlar.
