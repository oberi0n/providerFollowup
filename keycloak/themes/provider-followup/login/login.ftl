<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Provider Follow-up</title>
  <link rel="stylesheet" href="${url.resourcesPath}/css/login.css">
</head>
<body>
  <main class="login-shell">
    <section class="login-card" aria-label="Connexion Provider Follow-up">
      <h1>Provider Follow-up</h1>
      <#if message?has_content>
        <p class="login-message ${message.type}">${message.summary}</p>
      </#if>
      <form id="kc-form-login" class="login-form" action="${url.loginAction}" method="post">
        <label for="username">Utilisateur</label>
        <input id="username" name="username" type="text" value="${(login.username!'')}" autocomplete="username" autofocus>

        <label for="password">Mot de passe</label>
        <input id="password" name="password" type="password" autocomplete="current-password">

        <input type="hidden" id="id-hidden-input" name="credentialId" <#if auth.selectedCredential?has_content>value="${auth.selectedCredential}"</#if>>
        <button type="submit">Se connecter</button>
      </form>
    </section>
  </main>
</body>
</html>
