import { asset } from '@kit.AssetStoreKit';

const ASSET_ALIAS: Uint8Array = new TextEncoder().encode('vibescreen.last-paired-host');

export interface PairingTarget { host: string; port: number; offerId: string; credential: string; }

export class PairingLink {
  static parse(value: string): PairingTarget {
    const url: URL = new URL(value);
    if (url.protocol !== 'vibescreen:') throw new Error('Unsupported pairing scheme');
    const port: number = Number(url.searchParams.get('port'));
    const offerId: string = url.searchParams.get('offer') ?? '';
    const credential: string = url.searchParams.get('credential') ?? '';
    if (url.hostname.length === 0 || !Number.isInteger(port) || port < 1 || port > 65535 || offerId.length === 0 || credential.length === 0) {
      throw new Error('Incomplete pairing link');
    }
    return { host: url.hostname, port, offerId, credential };
  }
}

export class PairingStore {
  async save(target: PairingTarget): Promise<void> {
    await this.revoke();
    await asset.add({
      [asset.Tag.ALIAS]: ASSET_ALIAS,
      [asset.Tag.SECRET]: new TextEncoder().encode(JSON.stringify(target))
    });
  }

  async load(): Promise<PairingTarget | undefined> {
    const matches: asset.AssetMap[] = await asset.query({
      [asset.Tag.ALIAS]: ASSET_ALIAS,
      [asset.Tag.RETURN_TYPE]: asset.ReturnType.ALL
    });
    if (matches.length === 0) return undefined;
    const secret = matches[0][asset.Tag.SECRET] as Uint8Array;
    return JSON.parse(new TextDecoder().decode(secret)) as PairingTarget;
  }

  async revoke(): Promise<void> {
    const matches: asset.AssetMap[] = await asset.query({
      [asset.Tag.ALIAS]: ASSET_ALIAS,
      [asset.Tag.RETURN_TYPE]: asset.ReturnType.ATTRIBUTES
    });
    if (matches.length > 0) await asset.remove({ [asset.Tag.ALIAS]: ASSET_ALIAS });
  }
}
