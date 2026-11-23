/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 Alex White */

#include <gtk/gtk.h>
#include <glib/gstdio.h>
#include <pi-file.h>
#include <libxml/parser.h>
#include <string.h>
#include <unistd.h>

/* The host exports these functions from its plugin API. */
extern void jp_init(void);
extern int jp_get_home_file_name(const char *file, char *path, int size);
extern int jp_logf(int level, const char *format, ...);

enum { JP_LOG_INFO = 2, JP_LOG_WARN = 4 };

typedef struct {
    GtkListStore *feeds;
    GtkTreeSelection *selection;
    GtkWidget *entry;
    GtkWidget *status;
    char **urls;
    char path[FILENAME_MAX];
    gboolean loaded;
} FeedEditor;

static gboolean load_urls(const char *path, char ***urls, GError **error)
{
    g_autofree char *contents = NULL;
    g_autoptr(GError) read_error = NULL;
    if (!g_file_get_contents(path, &contents, NULL, &read_error)) {
        if (!g_error_matches(read_error, G_FILE_ERROR, G_FILE_ERROR_NOENT)) {
            g_propagate_error(error, g_steal_pointer(&read_error));
            return FALSE;
        }
        contents = g_strdup("");
    }
    *urls = g_strsplit(contents, "\n", -1);
    return TRUE;
}

static void refresh_feeds(FeedEditor *editor)
{
    gtk_list_store_clear(editor->feeds);
    for (char **url = editor->urls; *url; ++url) {
        if (**url)
            gtk_list_store_insert_with_values(editor->feeds, NULL, -1, 0, *url, -1);
    }
}

static gboolean save_feeds(FeedEditor *editor, GString *contents)
{
    g_autoptr(GError) error = NULL;
    if (!g_file_set_contents(editor->path, contents->str, contents->len, &error)) {
        gtk_label_set_text(GTK_LABEL(editor->status), error->message);
        return FALSE;
    }
    g_strfreev(editor->urls);
    editor->urls = g_strsplit(contents->str, "\n", -1);
    refresh_feeds(editor);
    gtk_label_set_text(GTK_LABEL(editor->status), "Saved for the next HotSync.");
    return TRUE;
}

static gboolean valid_feed_url(const char *url, gboolean allow_gemini)
{
    g_autoptr(GUri) uri = g_uri_parse(url, G_URI_FLAGS_NONE, NULL);
    const char *scheme = uri ? g_uri_get_scheme(uri) : NULL;
    return scheme && (g_str_equal(scheme, "http") || g_str_equal(scheme, "https") ||
                      (allow_gemini && g_str_equal(scheme, "gemini"))) &&
        !strpbrk(url, " \r\n\t") && g_uri_get_host(uri) && *g_uri_get_host(uri);
}

static void add_feed(GtkWidget *widget, FeedEditor *editor)
{
    (void)widget;
    if (!editor->loaded)
        return;

    g_autofree char *url = g_strdup(gtk_entry_get_text(GTK_ENTRY(editor->entry)));
    g_strstrip(url);
    if (!valid_feed_url(url, TRUE)) {
        gtk_label_set_text(GTK_LABEL(editor->status), "Enter an HTTP, HTTPS, or Gemini feed URL.");
        return;
    }
    if (g_strv_contains((const char * const *)editor->urls, url)) {
        gtk_label_set_text(GTK_LABEL(editor->status), "This feed is already in the list.");
        return;
    }
    g_autoptr(GString) contents = g_string_new(NULL);
    for (char **item = editor->urls; *item; ++item) {
        if (**item)
            g_string_append_printf(contents, "%s\n", *item);
    }
    g_string_append_printf(contents, "%s\n", url);
    if (save_feeds(editor, contents))
        gtk_entry_set_text(GTK_ENTRY(editor->entry), "");
}

static void remove_feed(GtkWidget *widget, FeedEditor *editor)
{
    (void)widget;
    GtkTreeModel *model;
    GtkTreeIter selected;
    if (!gtk_tree_selection_get_selected(editor->selection, &model, &selected))
        return;

    g_autofree char *url = NULL;
    gtk_tree_model_get(model, &selected, 0, &url, -1);
    g_autoptr(GString) contents = g_string_new(NULL);
    for (char **item = editor->urls; *item; ++item) {
        if (**item && !g_str_equal(*item, url))
            g_string_append_printf(contents, "%s\n", *item);
    }
    save_feeds(editor, contents);
}

static gboolean named(xmlNode *node, const char *name)
{
    return node && node->type == XML_ELEMENT_NODE && xmlStrEqual(node->name, BAD_CAST name);
}

static void collect_outlines(xmlNode *parent, GHashTable *seen, GString *contents, guint *added)
{
    for (xmlNode *node = parent->children; node; node = node->next) {
        if (!named(node, "outline"))
            continue;
        xmlChar *attr = xmlGetProp(node, BAD_CAST "xmlUrl");
        if (attr) {
            char *url = g_strstrip((char *)attr);
            if (valid_feed_url(url, FALSE) && g_hash_table_add(seen, g_strdup(url))) {
                g_string_append_printf(contents, "%s\n", url);
                ++*added;
            }
            xmlFree(attr);
        }
        collect_outlines(node, seen, contents, added);
    }
}

static void import_opml(FeedEditor *editor, const char *path)
{
    xmlDoc *doc = xmlReadFile(path, NULL, XML_PARSE_NONET | XML_PARSE_NOERROR | XML_PARSE_NOWARNING);
    xmlNode *root = doc ? xmlDocGetRootElement(doc) : NULL;
    xmlNode *body = NULL;
    if (named(root, "opml") && !doc->intSubset && !doc->extSubset) {
        for (body = root->children; body && !named(body, "body"); body = body->next) {}
    }
    if (!body) {
        gtk_label_set_text(GTK_LABEL(editor->status), "Could not read a supported OPML document.");
        xmlFreeDoc(doc);
        return;
    }
    g_autoptr(GHashTable) seen = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    g_autoptr(GString) contents = g_string_new(NULL);
    for (char **item = editor->urls; *item; ++item) {
        if (**item) {
            g_hash_table_add(seen, g_strdup(*item));
            g_string_append_printf(contents, "%s\n", *item);
        }
    }
    guint added = 0;
    collect_outlines(body, seen, contents, &added);
    xmlFreeDoc(doc);
    if (!added || save_feeds(editor, contents)) {
        g_autofree char *message = g_strdup_printf("Imported %u new feeds.", added);
        gtk_label_set_text(GTK_LABEL(editor->status), message);
    }
}

static void export_opml(FeedEditor *editor, const char *path)
{
    g_autoptr(GString) xml = g_string_new("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<opml version=\"2.0\"><head><title>Feeds to Plucker</title></head><body>\n");
    for (char **item = editor->urls; *item; ++item) {
        if (valid_feed_url(*item, FALSE)) {
            g_autofree char *url = g_markup_escape_text(*item, -1);
            g_string_append_printf(xml, "  <outline type=\"rss\" text=\"%s\" xmlUrl=\"%s\"/>\n", url, url);
        }
    }
    g_string_append(xml, "</body></opml>\n");
    g_autoptr(GError) error = NULL;
    gboolean saved = g_file_set_contents(path, xml->str, xml->len, &error);
    gtk_label_set_text(GTK_LABEL(editor->status), saved ? "Exported subscriptions." : error->message);
}

static void choose_opml(GtkButton *button, FeedEditor *editor)
{
    gboolean exporting = GPOINTER_TO_INT(g_object_get_data(G_OBJECT(button), "export"));
    GtkWidget *dialog = gtk_file_chooser_dialog_new(gtk_button_get_label(button),
        GTK_WINDOW(gtk_widget_get_toplevel(GTK_WIDGET(button))),
        exporting ? GTK_FILE_CHOOSER_ACTION_SAVE : GTK_FILE_CHOOSER_ACTION_OPEN,
        "_Cancel", GTK_RESPONSE_CANCEL, exporting ? "_Save" : "_Open", GTK_RESPONSE_ACCEPT, NULL);
    GtkFileChooser *chooser = GTK_FILE_CHOOSER(dialog);
    if (exporting) {
        gtk_file_chooser_set_current_name(chooser, "subscriptions.opml");
        gtk_file_chooser_set_do_overwrite_confirmation(chooser, TRUE);
    }
    if (gtk_dialog_run(GTK_DIALOG(dialog)) == GTK_RESPONSE_ACCEPT) {
        g_autofree char *path = gtk_file_chooser_get_filename(chooser);
        if (exporting)
            export_opml(editor, path);
        else
            import_opml(editor, path);
    }
    gtk_widget_destroy(dialog);
}

static void free_editor(gpointer data)
{
    FeedEditor *editor = data;
    g_object_unref(editor->feeds);
    g_strfreev(editor->urls);
    g_free(editor);
}

void plugin_version(int *major, int *minor)
{
    *major = 1;
    *minor = 0;
}

int plugin_get_name(char *name, int len)
{
    g_strlcpy(name, "Feeds to Plucker 1.0", len);
    return 0;
}

int plugin_get_menu_name(char *name, int len)
{
    g_strlcpy(name, "Feeds to Plucker", len);
    return 0;
}

int plugin_startup(void *info)
{
    (void)info;
    jp_init();
    return 0;
}

int plugin_gui(GtkWidget *sidebar, GtkWidget *main, unsigned int id)
{
    (void)sidebar;
    (void)id;
    FeedEditor *editor = g_new0(FeedEditor, 1);
    GtkWidget *panel = gtk_box_new(GTK_ORIENTATION_VERTICAL, 8);
    gtk_container_set_border_width(GTK_CONTAINER(panel), 12);
    gtk_box_pack_start(GTK_BOX(main), panel, TRUE, TRUE, 0);
    g_object_set_data_full(G_OBJECT(panel), "rss-feed-editor", editor, free_editor);

    GtkWidget *controls = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    gtk_box_pack_start(GTK_BOX(panel), controls, FALSE, FALSE, 0);
    editor->entry = gtk_entry_new();
    gtk_entry_set_placeholder_text(GTK_ENTRY(editor->entry), "Feed URL");
    gtk_widget_set_tooltip_text(editor->entry, "RSS or Atom feed URL, or gemini:// Gemsub URL");
    gtk_box_pack_start(GTK_BOX(controls), editor->entry, TRUE, TRUE, 0);
    GtkWidget *add = gtk_button_new_with_label("Add Feed");
    GtkWidget *remove = gtk_button_new_with_label("Remove Selected");
    gtk_box_pack_start(GTK_BOX(controls), add, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(controls), remove, FALSE, FALSE, 0);

    editor->feeds = gtk_list_store_new(1, G_TYPE_STRING);
    GtkWidget *view = gtk_tree_view_new_with_model(GTK_TREE_MODEL(editor->feeds));
    GtkCellRenderer *renderer = gtk_cell_renderer_text_new();
    g_object_set(renderer, "ellipsize", PANGO_ELLIPSIZE_END, NULL);
    gtk_tree_view_insert_column_with_attributes(GTK_TREE_VIEW(view), -1,
        "Subscribed Feeds", renderer, "text", 0, NULL);
    editor->selection = gtk_tree_view_get_selection(GTK_TREE_VIEW(view));
    GtkWidget *scroll = gtk_scrolled_window_new(NULL, NULL);
    gtk_container_add(GTK_CONTAINER(scroll), view);
    gtk_box_pack_start(GTK_BOX(panel), scroll, TRUE, TRUE, 0);

    editor->status = gtk_label_new("Today's articles are sent to Plucker at each HotSync.");
    gtk_label_set_xalign(GTK_LABEL(editor->status), 0);
    gtk_label_set_line_wrap(GTK_LABEL(editor->status), TRUE);
    gtk_box_pack_start(GTK_BOX(panel), editor->status, FALSE, FALSE, 0);

    g_autoptr(GError) error = NULL;
    jp_get_home_file_name("rss-plucker-feeds.txt", editor->path, sizeof(editor->path));
    editor->loaded = load_urls(editor->path, &editor->urls, &error);
    if (editor->loaded)
        refresh_feeds(editor);
    else
        gtk_label_set_text(GTK_LABEL(editor->status), error->message);
    GtkWidget *actions = gtk_box_new(GTK_ORIENTATION_HORIZONTAL, 8);
    gtk_box_pack_start(GTK_BOX(panel), actions, FALSE, FALSE, 0);
    GtkWidget *import = gtk_button_new_with_label("Import OPML");
    GtkWidget *export = gtk_button_new_with_label("Export OPML");
    g_object_set_data(G_OBJECT(export), "export", GINT_TO_POINTER(TRUE));
    gtk_box_pack_start(GTK_BOX(actions), import, FALSE, FALSE, 0);
    gtk_box_pack_start(GTK_BOX(actions), export, FALSE, FALSE, 0);
    gtk_widget_set_sensitive(actions, editor->loaded);
    g_signal_connect(import, "clicked", G_CALLBACK(choose_opml), editor);
    g_signal_connect(export, "clicked", G_CALLBACK(choose_opml), editor);
    gtk_widget_set_sensitive(add, editor->loaded);
    gtk_widget_set_sensitive(remove, editor->loaded);
    g_signal_connect(add, "clicked", G_CALLBACK(add_feed), editor);
    g_signal_connect(editor->entry, "activate", G_CALLBACK(add_feed), editor);
    g_signal_connect(remove, "clicked", G_CALLBACK(remove_feed), editor);
    gtk_widget_show_all(main);
    return 0;
}

int plugin_sync(int sd)
{
    char script[FILENAME_MAX], feeds[FILENAME_MAX];
    jp_get_home_file_name("plugins/rss_plucker.py", script, sizeof(script));
    jp_get_home_file_name("rss-plucker-feeds.txt", feeds, sizeof(feeds));

    g_autoptr(GError) error = NULL;
    g_autofree char *path = NULL;
    int fd = g_file_open_tmp("jpilot-rss-XXXXXX", &path, &error);
    if (fd < 0) {
        jp_logf(JP_LOG_WARN, "Feeds to Plucker: %s\n", error->message);
        return -1;
    }
    close(fd);

    char *argv[] = {"python3", "-u", script, feeds, path, NULL};
    g_autofree char *output = NULL;
    g_autofree char *diagnostics = NULL;
    int status;
    gboolean built = g_spawn_sync(NULL, argv, NULL, G_SPAWN_SEARCH_PATH,
        NULL, NULL, &output, &diagnostics, &status, &error) &&
        g_spawn_check_wait_status(status, &error);
    if (diagnostics && *diagnostics)
        jp_logf(JP_LOG_WARN, "%s", diagnostics);

    int result = -1;
    if (!built) {
        jp_logf(JP_LOG_WARN, "Feeds to Plucker: %s\n", error->message);
    } else {
        pi_file_t *file = pi_file_open(path);
        if (file) {
            result = pi_file_install(file, sd, 0, NULL);
            pi_file_close(file);
        }
        if (result < 0)
            jp_logf(JP_LOG_WARN, "Feeds to Plucker: could not install the daily document (%d).\n", result);
        else if (output && *output)
            jp_logf(JP_LOG_INFO, "%s", output);
    }

    g_unlink(path);
    return result < 0 ? -1 : 0;
}
