# QA branch ONLY. The addon source comes exclusively from the verified customer ZIP.
FROM odoo:19.0
USER root
COPY qa_wati/WATI-Odoo-19-19.0.11.0.9.zip /tmp/wati-release.zip
RUN echo '147c1cc6ce5902ebae8ea8bfd10a5fc01f55da26b8e6144268291dda41b88c2d  /tmp/wati-release.zip' | sha256sum -c - \
 && python3 -c 'import pathlib,shutil,zipfile; p=pathlib.Path("/tmp/wati-release.zip"); root=pathlib.Path("/tmp/wati-extract"); z=zipfile.ZipFile(p); assert z.testzip() is None; z.extractall(root); src=root/"WATI-Odoo-19-19.0.11.0.9"/"addons"; expected={"wati_connector","wati_connector_crm","wati_connector_sale","wati_connector_account","wati_connector_project"}; assert {x.name for x in src.iterdir() if x.is_dir()}==expected; shutil.copytree(src,"/mnt/extra-addons",dirs_exist_ok=True)' \
 && rm -rf /tmp/wati-release.zip /tmp/wati-extract \
 && chown -R odoo:odoo /mnt/extra-addons
COPY qa_wati/run-odoo.sh /usr/local/bin/run-wati-odoo
COPY qa_wati/install-core.py /usr/local/bin/install-wati-core.py
RUN chmod 755 /usr/local/bin/run-wati-odoo /usr/local/bin/install-wati-core.py
USER odoo
EXPOSE 8069
ENTRYPOINT ["/usr/local/bin/run-wati-odoo"]
CMD []
