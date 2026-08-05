import { asset } from '@kit.AssetStoreKit';
import { JSON, url, util } from '@kit.ArkTS';

const HOST_ALIAS: Uint8Array = new util.TextEncoder().encode('vibescreen.trusted-lan-host.v1');
const IDENTITY_ALIAS: Uint8Array = new util.TextEncoder().encode('vibescreen.client-identity.v1');
const RECORD_VERSION: number = 1;

export interface PairingTarget { host: string; port: number; offerId: string; oneTimeCredential: string; }
export interface TrustedHostRecord { version: number; host: string; port: number; offerId: string; }

export class PairingLink {
  static parse(value: string): PairingTarget {
    const parsed: url.URL = url.URL.parseURL(value.trim());
    if (parsed.protocol !== 'vibescreen:') throw new Error('仅支持 vibescreen:// 配对链接');
    const port: number = Number(parsed.searchParams.get('port'));
    const offerId: string = parsed.searchParams.get('offer') ?? '';
    const credential: string = parsed.searchParams.get('credential') ?? '';
    if (parsed.hostname.length === 0 || !Number.isInteger(port) || port < 1 || port > 65535 || offerId.length === 0 || credential.length === 0) {
      throw new Error('配对链接不完整或已损坏');
    }
    return { host: parsed.hostname, port, offerId, oneTimeCredential: credential };
  }
}

export class PairingStore {
  async saveTrustedHost(target: PairingTarget): Promise<void> {
    // The one-time credential is deliberately not persisted. Full proof exchange remains host-gated.
    const record: TrustedHostRecord = { version: RECORD_VERSION, host: target.host, port: target.port, offerId: target.offerId };
    await this.replace(HOST_ALIAS, new util.TextEncoder().encode(JSON.stringify(record)));
  }

  async loadTrustedHost(): Promise<TrustedHostRecord | undefined> {
    const secret: Uint8Array | undefined = await this.loadSecret(HOST_ALIAS);
    if (secret === undefined) return undefined;
    try {
      const raw = JSON.parse(new util.TextDecoder().decode(secret)) as Partial<TrustedHostRecord>;
      if (raw.version !== RECORD_VERSION || typeof raw.host !== 'string' || raw.host.length === 0 ||
        !Number.isInteger(raw.port) || (raw.port as number) < 1 || (raw.port as number) > 65535 || typeof raw.offerId !== 'string') {
        throw new Error('unsupported_record');
      }
      return raw as TrustedHostRecord;
    } catch (_error) {
      await this.remove(HOST_ALIAS);
      throw new Error('已保存的主机记录损坏或版本不受支持');
    }
  }

  async clientId(): Promise<string> {
    const stored: Uint8Array | undefined = await this.loadSecret(IDENTITY_ALIAS);
    if (stored !== undefined) return new util.TextDecoder().decode(stored);
    const generated: string = `harmony-${util.generateRandomUUID(true)}`;
    await this.replace(IDENTITY_ALIAS, new util.TextEncoder().encode(generated));
    return generated;
  }

  async forgetHost(): Promise<void> { await this.remove(HOST_ALIAS); }

  private async replace(alias: Uint8Array, secret: Uint8Array): Promise<void> {
    await this.remove(alias);
    const attributes: asset.AssetMap = new Map();
    attributes.set(asset.Tag.ALIAS, alias); attributes.set(asset.Tag.SECRET, secret);
    await asset.add(attributes);
  }

  private async loadSecret(alias: Uint8Array): Promise<Uint8Array | undefined> {
    const query: asset.AssetMap = new Map();
    query.set(asset.Tag.ALIAS, alias); query.set(asset.Tag.RETURN_TYPE, asset.ReturnType.ALL);
    const matches: asset.AssetMap[] = await asset.query(query);
    if (matches.length === 0) return undefined;
    return matches[0].get(asset.Tag.SECRET) as Uint8Array;
  }

  private async remove(alias: Uint8Array): Promise<void> {
    const query: asset.AssetMap = new Map();
    query.set(asset.Tag.ALIAS, alias); query.set(asset.Tag.RETURN_TYPE, asset.ReturnType.ATTRIBUTES);
    const matches: asset.AssetMap[] = await asset.query(query);
    if (matches.length > 0) { const removeQuery: asset.AssetMap = new Map(); removeQuery.set(asset.Tag.ALIAS, alias); await asset.remove(removeQuery); }
  }
}
