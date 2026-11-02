<?php
/**
 * Plugin Name: FPH Connect
 * Description: Reçoit les églises publiées depuis le serveur FPH Connect. Ajoute un type de contenu séparé (fph_church) : n'altère aucune page ni article existant.
 * Version: 0.1.0
 * Requires PHP: 7.4
 * License: GPL-2.0-or-later
 *
 * CONFIGURATION (wp-config.php, jamais dans la base de données) :
 *   define('FPH_SYNC_SECRET', '...secret fourni par le serveur FPH...');
 *   define('FPH_SYNC_DISABLED', true);   // interrupteur d'urgence (facultatif)
 *   // Pour les inscriptions aux événements (site -> serveur FPH) :
 *   define('FPH_API_URL', 'https://fph-serveur.exemple.org');
 *   define('FPH_INTEGRATION_ID', '...identifiant de l\'intégration FPH...');
 *
 * STATUT : écrit selon le protocole docs/WEB_CONNECTOR_PROTOCOL.md ; NON TESTÉ dans WordPress (PHP absent de l'environnement de développement).
 */

if (!defined('ABSPATH')) { exit; }

const FPH_TOLERANCE_SECONDS = 300;

add_action('init', function () {
    register_post_type('fph_church', [
        'label'        => 'Églises FPH',
        'public'       => true,
        'has_archive'  => true,
        'rewrite'      => ['slug' => 'eglises'],
        'supports'     => ['title', 'editor'],
        'show_in_rest' => false,
        'menu_icon'    => 'dashicons-location',
    ]);
    register_post_type('fph_event', [
        'label'        => 'Événements FPH',
        'public'       => true,
        'has_archive'  => true,
        'rewrite'      => ['slug' => 'evenements'],
        'supports'     => ['title', 'editor'],
        'show_in_rest' => false,
        'menu_icon'    => 'dashicons-calendar-alt',
    ]);
});

add_action('rest_api_init', function () {
    register_rest_route('fph/v1', '/sync', [
        'methods'             => 'POST',
        'callback'            => 'fph_handle_sync',
        'permission_callback' => 'fph_verify_request',   // signature HMAC, pas de session WP
    ]);
});

function fph_verify_request(WP_REST_Request $req) {
    if (defined('FPH_SYNC_DISABLED') && FPH_SYNC_DISABLED) {
        return new WP_Error('fph_disabled', 'Synchronisation désactivée', ['status' => 503]);
    }
    if (!defined('FPH_SYNC_SECRET') || strlen(FPH_SYNC_SECRET) < 32) {
        return new WP_Error('fph_not_configured', 'Secret non configuré', ['status' => 503]);
    }
    $body = $req->get_body();
    if (strlen($body) > 65536) {
        return new WP_Error('fph_too_large', 'Corps trop volumineux', ['status' => 413]);
    }
    $ts  = $req->get_header('x-fph-timestamp');
    $sig = (string) $req->get_header('x-fph-signature');
    if (!ctype_digit((string) $ts) || abs(time() - (int) $ts) > FPH_TOLERANCE_SECONDS) {
        return new WP_Error('fph_bad_signature', 'Signature invalide', ['status' => 401]);
    }
    $expected = 'sha256=' . hash_hmac('sha256', $ts . '.' . $body, FPH_SYNC_SECRET);
    if (!hash_equals($expected, $sig)) {
        return new WP_Error('fph_bad_signature', 'Signature invalide', ['status' => 401]);
    }
    return true;
}

function fph_find_post($entity_id, $type = 'fph_church') {
    $q = new WP_Query([
        'post_type' => $type, 'post_status' => 'any', 'posts_per_page' => 1,
        'meta_key' => '_fph_id', 'meta_value' => $entity_id, 'fields' => 'ids',
        'no_found_rows' => true,
    ]);
    return $q->posts ? (int) $q->posts[0] : 0;
}

function fph_handle_sync(WP_REST_Request $req) {
    $msg = json_decode($req->get_body(), true);
    $kind = is_array($msg) ? ($msg['kind'] ?? 'church') : '';
    $raw_id = is_array($msg) ? ($msg['entity_id'] ?? $msg['church_id'] ?? $msg['event_id'] ?? null) : null;
    if (!is_array($msg) || $raw_id === null || !isset($msg['seq'], $msg['action'])
        || !in_array($kind, ['church', 'event'], true)
        || !in_array($msg['action'], ['upsert', 'remove'], true)
        || ($msg['action'] === 'upsert' && !is_array($msg['data'] ?? null))) {
        return new WP_REST_Response(['error' => 'invalid payload'], 422);
    }
    $cid = sanitize_text_field((string) $raw_id);
    $seq = (int) $msg['seq'];
    $ptype = ($kind === 'event') ? 'fph_event' : 'fph_church';
    $post_id = fph_find_post($cid, $ptype);

    // Message obsolète ou rejoué : ignoré (idempotence + ordre)
    if ($post_id && $seq <= (int) get_post_meta($post_id, '_fph_seq', true)) {
        return new WP_REST_Response(['status' => 'ignored_stale'], 200);
    }

    if ($msg['action'] === 'remove') {
        if ($post_id) {               // brouillon (réversible), jamais de suppression
            wp_update_post(['ID' => $post_id, 'post_status' => 'draft']);
            update_post_meta($post_id, '_fph_seq', $seq);
        }
        return new WP_REST_Response(['status' => 'applied'], 200);
    }

    $d = $msg['data'];
    $content = '';
    if ($kind === 'event') {
        $fields = ['starts_at' => 'Début', 'ends_at' => 'Fin', 'location' => 'Lieu',
                   'department' => 'Département'];
        $title = sanitize_text_field((string) ($d['title'] ?? 'Événement'));
        if (!empty($d['description'])) {
            $content .= '<p>' . esc_html((string) $d['description']) . '</p>';
        }
    } else {
        $fields = ['address' => 'Adresse', 'commune' => 'Commune', 'department' => 'Département',
                   'contact_phone' => 'Téléphone'];
        $title = sanitize_text_field((string) ($d['official_name'] ?? 'Église'));
    }
    foreach ($fields as $k => $label) {
        if (!empty($d[$k])) {
            $content .= '<p><strong>' . esc_html($label) . ' :</strong> ' . esc_html((string) $d[$k]) . '</p>';
        }
    }
    $postarr = [
        'post_type' => $ptype, 'post_status' => 'publish',
        'post_title' => $title, 'post_content' => $content,
    ];
    if ($post_id) { $postarr['ID'] = $post_id; $post_id = wp_update_post($postarr, true); }
    else          { $post_id = wp_insert_post($postarr, true); }
    if (is_wp_error($post_id)) {
        return new WP_REST_Response(['error' => 'write failed'], 500);   // l'expéditeur réessaiera
    }
    update_post_meta($post_id, '_fph_id', $cid);
    update_post_meta($post_id, '_fph_seq', $seq);
    update_post_meta($post_id, '_fph_department', sanitize_text_field((string) ($d['department'] ?? '')));
    if ($kind === 'event') {
        update_post_meta($post_id, '_fph_registration_open', !empty($d['registration_open']) ? '1' : '0');
        update_post_meta($post_id, '_fph_starts_at', sanitize_text_field((string) ($d['starts_at'] ?? '')));
    }
    return new WP_REST_Response(['status' => 'applied'], 200);
}

// Shortcode : [fph_churches department="Ouest"]
add_shortcode('fph_churches', function ($atts) {
    $atts = shortcode_atts(['department' => ''], $atts);
    $args = ['post_type' => 'fph_church', 'post_status' => 'publish', 'posts_per_page' => 200,
             'orderby' => 'title', 'order' => 'ASC'];
    if ($atts['department'] !== '') {
        $args['meta_key'] = '_fph_department';
        $args['meta_value'] = sanitize_text_field($atts['department']);
    }
    $q = new WP_Query($args);
    if (!$q->have_posts()) { return '<p>Aucune église à afficher.</p>'; }
    $out = '<ul class="fph-churches">';
    while ($q->have_posts()) {
        $q->the_post();
        $out .= '<li><a href="' . esc_url(get_permalink()) . '">' . esc_html(get_the_title()) . '</a></li>';
    }
    wp_reset_postdata();
    return $out . '</ul>';
});


// Shortcode : [fph_events]
add_shortcode('fph_events', function () {
    $q = new WP_Query(['post_type' => 'fph_event', 'post_status' => 'publish', 'posts_per_page' => 100,
                       'meta_key' => '_fph_starts_at', 'orderby' => 'meta_value', 'order' => 'ASC']);
    if (!$q->have_posts()) { return '<p>Aucun événement à afficher.</p>'; }
    $out = '<ul class="fph-events">';
    while ($q->have_posts()) {
        $q->the_post();
        $out .= '<li><a href="' . esc_url(get_permalink()) . '">' . esc_html(get_the_title()) . '</a></li>';
    }
    wp_reset_postdata();
    return $out . '</ul>';
});

// ---------------- Inscriptions : formulaire du site -> serveur FPH (signé, côté serveur WordPress) ----------------
function fph_registration_messages() {
    return [
        'registered' => 'Votre inscription est enregistrée.',
        'waitlisted' => 'L\'événement est complet : vous êtes sur liste d\'attente.',
        'closed'     => 'Les inscriptions sont fermées pour cet événement.',
        'invalid'    => 'Formulaire incomplet : nom, e-mail ou téléphone, et consentement sont requis.',
        'error'      => 'Une erreur est survenue. Veuillez réessayer plus tard.',
    ];
}

// [fph_event_registration] (sur la page d'un événement) ou [fph_event_registration event="ID-FPH"]
add_shortcode('fph_event_registration', function ($atts) {
    $atts = shortcode_atts(['event' => ''], $atts);
    $event_id = $atts['event'] !== '' ? sanitize_text_field($atts['event'])
              : (string) get_post_meta(get_the_ID(), '_fph_id', true);
    $msgs = fph_registration_messages();
    $out = '';
    $res = isset($_GET['fph_result']) ? sanitize_key(wp_unslash($_GET['fph_result'])) : '';
    if ($res !== '' && isset($msgs[$res])) {
        $out .= '<p class="fph-result">' . esc_html($msgs[$res]) . '</p>';
    }
    $open = $atts['event'] !== '' ? true : get_post_meta(get_the_ID(), '_fph_registration_open', true) === '1';
    if ($event_id === '' || !$open) { return $out . '<p>Inscriptions fermées.</p>'; }
    $out .= '<form method="post" action="' . esc_url(admin_url('admin-post.php')) . '" class="fph-registration">';
    $out .= '<input type="hidden" name="action" value="fph_register">';
    $out .= '<input type="hidden" name="fph_event" value="' . esc_attr($event_id) . '">';
    $out .= '<input type="hidden" name="fph_idem" value="' . esc_attr(wp_generate_uuid4()) . '">';
    $out .= '<input type="hidden" name="fph_back" value="' . esc_url(get_permalink()) . '">';
    $out .= wp_nonce_field('fph_register', 'fph_nonce', true, false);
    $out .= '<p style="display:none"><input type="text" name="fph_website" tabindex="-1" autocomplete="off"></p>';  // piège à robots
    $out .= '<p><label>Nom complet <input type="text" name="fph_name" required maxlength="200"></label></p>';
    $out .= '<p><label>E-mail <input type="email" name="fph_email" maxlength="255"></label></p>';
    $out .= '<p><label>Téléphone <input type="text" name="fph_phone" maxlength="50"></label></p>';
    $out .= '<p><label><input type="checkbox" name="fph_consent" value="1" required> J\'accepte que mes données soient utilisées pour cet événement.</label></p>';
    $out .= '<p><button type="submit">S\'inscrire</button></p></form>';
    return $out;
});

add_action('admin_post_nopriv_fph_register', 'fph_handle_registration_form');
add_action('admin_post_fph_register', 'fph_handle_registration_form');

function fph_handle_registration_form() {
    $back = isset($_POST['fph_back']) ? esc_url_raw(wp_unslash($_POST['fph_back'])) : home_url('/');
    $back = wp_validate_redirect($back, home_url('/'));          // pas de redirection vers un autre site
    $go = function ($result) use ($back) { wp_safe_redirect(add_query_arg('fph_result', $result, $back)); exit; };
    if (!isset($_POST['fph_nonce']) || !wp_verify_nonce(sanitize_text_field(wp_unslash($_POST['fph_nonce'])), 'fph_register')) {
        $go('error');
    }
    if (!empty($_POST['fph_website'])) { $go('registered'); }    // robot : on fait semblant, rien n'est envoyé
    if (!defined('FPH_API_URL') || !defined('FPH_INTEGRATION_ID') || !defined('FPH_SYNC_SECRET')) { $go('error'); }
    $payload = [
        'event_id'  => sanitize_text_field(wp_unslash($_POST['fph_event'] ?? '')),
        'full_name' => sanitize_text_field(wp_unslash($_POST['fph_name'] ?? '')),
        'email'     => sanitize_email(wp_unslash($_POST['fph_email'] ?? '')) ?: null,
        'phone'     => sanitize_text_field(wp_unslash($_POST['fph_phone'] ?? '')) ?: null,
        'consent'   => !empty($_POST['fph_consent']),
    ];
    if ($payload['full_name'] === '' || !$payload['consent'] || (!$payload['email'] && !$payload['phone'])) { $go('invalid'); }
    $idem = sanitize_text_field(wp_unslash($_POST['fph_idem'] ?? '')) ?: wp_generate_uuid4();
    ksort($payload);
    $body = wp_json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    $ts = (string) time();
    $resp = wp_remote_post(rtrim(FPH_API_URL, '/') . '/api/v1/inbound/' . rawurlencode(FPH_INTEGRATION_ID) . '/registrations', [
        'timeout' => 10, 'redirection' => 0,
        'headers' => ['Content-Type' => 'application/json', 'X-FPH-Timestamp' => $ts,
                      'X-FPH-Idempotency-Key' => $idem,
                      'X-FPH-Signature' => 'sha256=' . hash_hmac('sha256', $ts . '.' . $body, FPH_SYNC_SECRET)],
        'body' => $body,
    ]);
    if (is_wp_error($resp)) { $go('error'); }
    $code = wp_remote_retrieve_response_code($resp);
    $data = json_decode(wp_remote_retrieve_body($resp), true);
    if ($code === 200 && isset($data['status']) && in_array($data['status'], ['registered', 'waitlisted'], true)) { $go($data['status']); }
    if ($code === 200 && ($data['status'] ?? '') === 'dry_run') { $go('registered'); }
    if ($code === 409) { $go('closed'); }
    if ($code === 422) { $go('invalid'); }
    $go('error');
}
